#!/usr/bin/env python3
"""Server-side review state for the HiTL Explorer (M20.5, #114) — v1.

Design constraints, in order:
- decisions are an append-only event log (scholarly audit trail); the
  "current" adjudication is a view over events, never an overwrite;
- the export endpoint emits exactly the array format the pipeline already
  ingests via --review-decisions-path, so nothing downstream changes;
- stdlib only (ThreadingHTTPServer + sqlite3): no new pinned deps, and a
  service small enough for tei's 3.8 GB;
- binds loopback; nginx terminates TLS at /outremer/api/ (#123 snippet
  proxies to 127.0.0.1:8089). Writes need X-Review-Token when
  REVIEW_API_TOKEN is set; reads are open (the corpus itself is public).

Run:  python scripts/review_api.py --db /path/reviews.db --port 8089
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VALID_DECISIONS = {"accept", "reject", "not_a_person", "wrong_era", "is_group", "flag"}
_MAX_BODY = 64 * 1024

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id TEXT NOT NULL,
  person TEXT NOT NULL,
  outremer_id TEXT NOT NULL DEFAULT '',
  decision TEXT NOT NULL,
  client_id TEXT NOT NULL DEFAULT 'anonymous',
  scholar_name TEXT,
  comment TEXT,
  submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_key ON decision_events(doc_id, person, outremer_id);
"""


class ReviewStore:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def append(self, ev: dict) -> dict:
        doc_id = str(ev.get("doc_id") or "").strip()
        person = " ".join(str(ev.get("person") or "").split())
        decision = str(ev.get("decision") or "").strip()
        if not doc_id or not person:
            raise ValueError("doc_id and person are required")
        if decision not in VALID_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(VALID_DECISIONS)}")
        row = (
            doc_id, person, str(ev.get("outremer_id") or "").strip(), decision,
            str(ev.get("client_id") or "anonymous").strip()[:80],
            (str(ev.get("scholar_name")).strip()[:120] if ev.get("scholar_name") else None),
            (str(ev.get("comment")).strip()[:2000] if ev.get("comment") else None),
            datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO decision_events (doc_id, person, outremer_id, decision,"
                " client_id, scholar_name, comment, submitted_at)"
                " VALUES (?,?,?,?,?,?,?,?)", row)
            self._conn.commit()
        return {"id": cur.lastrowid, "submitted_at": row[-1]}

    def current(self, doc_id: str | None = None) -> list[dict]:
        """Latest event per (doc_id, person, outremer_id, client_id)."""
        q = ("SELECT doc_id, person, outremer_id, decision, client_id,"
             " scholar_name, comment, submitted_at FROM decision_events e"
             " WHERE id = (SELECT MAX(id) FROM decision_events"
             "  WHERE doc_id=e.doc_id AND person=e.person"
             "  AND outremer_id=e.outremer_id AND client_id=e.client_id)")
        args: tuple = ()
        if doc_id:
            q += " AND doc_id=?"
            args = (doc_id,)
        with self._lock:
            rows = self._conn.execute(q + " ORDER BY id", args).fetchall()
        keys = ["doc_id", "person", "outremer_id", "decision", "client_id",
                "scholar_name", "comment", "submitted_at"]
        return [dict(zip(keys, r)) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM decision_events").fetchone()[0]
        return {"events": n}


def make_handler(store: ReviewStore, token: str | None, cors_origin: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "outremer-review/1"

        def _send(self, code: int, payload: dict | list):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if cors_origin:
                self.send_header("Access-Control-Allow-Origin", cors_origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Review-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # keep journald tidy
            pass

        def do_OPTIONS(self):
            self._send(204, {})

        def do_GET(self):
            path, _, query = self.path.partition("?")
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            if path in ("/health", "/"):
                self._send(200, {"status": "ok", **store.stats()})
            elif path == "/decisions":
                self._send(200, store.current(params.get("doc_id")))
            elif path == "/export":
                # pipeline-facing: 'flag' is a review-UI state, not an
                # adjudication the importer understands — exclude it unless
                # explicitly requested
                rows = store.current(None)
                if params.get("include_flags") != "1":
                    rows = [r for r in rows if r["decision"] != "flag"]
                self._send(200, rows)
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path.partition("?")[0] != "/decisions":
                self._send(404, {"error": "not found"})
                return
            if token and self.headers.get("X-Review-Token") != token:
                self._send(401, {"error": "missing or wrong X-Review-Token"})
                return
            try:
                length = min(int(self.headers.get("Content-Length", 0)), _MAX_BODY)
                ev = json.loads(self.rfile.read(length) or b"{}")
                self._send(201, store.append(ev))
            except (ValueError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)})

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.environ.get("REVIEW_DB", "reviews.db"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("REVIEW_API_PORT", "8089")))
    ap.add_argument("--cors-origin", default=os.environ.get("REVIEW_CORS_ORIGIN", "https://thodel.github.io"))
    args = ap.parse_args(argv)
    store = ReviewStore(args.db)
    token = os.environ.get("REVIEW_API_TOKEN") or None
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(store, token, args.cors_origin))
    print(f"review api on http://{args.host}:{args.port} db={args.db} token={'set' if token else 'OPEN (writes unprotected)'}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
