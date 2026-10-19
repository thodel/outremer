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

v2 (M13.3, #179) closes the round trip Explorer → API → data/decisions.json:
- the Explorer posts here directly (no more localStorage-only);
- a withdrawal (DELETE) is itself an event — ``unresolved`` by the same
  reviewer — never a row deletion; ``supersedes`` is accepted and exported;
- GET /events?since=<iso> hands the importer (scripts/import_review_decisions.py)
  the full log after a timestamp, so nothing is lost between nights.

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

# "flag" is a review-UI state the pipeline never imports; "unresolved" is
# the validator's retirement verdict (M19.0) and what a withdrawal becomes.
VALID_DECISIONS = {"accept", "reject", "not_a_person", "wrong_era", "is_group", "flag", "unresolved"}
WITHDRAWN = "withdrawn in the Explorer"
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
  submitted_at TEXT NOT NULL,
  supersedes INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_key ON decision_events(doc_id, person, outremer_id);
"""
_COLUMNS = ["doc_id", "person", "outremer_id", "decision", "client_id",
            "scholar_name", "comment", "submitted_at", "supersedes"]


class ReviewStore:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        # v1 databases (tei, 29.08.2026) predate the column.
        have = {r[1] for r in self._conn.execute("PRAGMA table_info(decision_events)")}
        if "supersedes" not in have:
            self._conn.execute(
                "ALTER TABLE decision_events ADD COLUMN supersedes INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()
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
            1 if ev.get("supersedes") is True else 0,
        )
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO decision_events (doc_id, person, outremer_id, decision,"
                " client_id, scholar_name, comment, submitted_at, supersedes)"
                " VALUES (?,?,?,?,?,?,?,?,?)", row)
            self._conn.commit()
        return {"id": cur.lastrowid, "submitted_at": row[7]}

    def withdraw(self, ev: dict) -> dict:
        """A reviewer takes a decision back: an ``unresolved`` event by the same
        client, never a deletion. It carries no ``supersedes``, so other
        reviewers' decisions on the pair stay in force (per-reviewer rule in
        validate_decisions.effective_decisions)."""
        return self.append({
            "doc_id": ev.get("doc_id"), "person": ev.get("person"),
            "outremer_id": ev.get("outremer_id"), "decision": "unresolved",
            "client_id": ev.get("client_id"), "scholar_name": ev.get("scholar_name"),
            "comment": WITHDRAWN,
        })

    @staticmethod
    def _rows(rows: list[tuple]) -> list[dict]:
        out = []
        for r in rows:
            d = dict(zip(_COLUMNS, r))
            d["supersedes"] = bool(d["supersedes"])
            if not d["supersedes"]:
                del d["supersedes"]  # the file format only carries it when true
            out.append(d)
        return out

    def events(self, since: str | None = None, include_flags: bool = False) -> list[dict]:
        """The full log in id order, optionally only events after ``since``
        (ISO timestamp, exclusive). This is what the nightly imports."""
        q = f"SELECT {', '.join(_COLUMNS)} FROM decision_events"
        args: tuple = ()
        if since:
            q += " WHERE submitted_at > ?"
            args = (since,)
        with self._lock:
            rows = self._conn.execute(q + " ORDER BY id", args).fetchall()
        out = self._rows(rows)
        if not include_flags:
            out = [r for r in out if r["decision"] != "flag"]
        return out

    def current(self, doc_id: str | None = None) -> list[dict]:
        """Latest event per (doc_id, person, outremer_id, client_id)."""
        q = (f"SELECT {', '.join(_COLUMNS)} FROM decision_events e"
             " WHERE id = (SELECT MAX(id) FROM decision_events"
             "  WHERE doc_id=e.doc_id AND person=e.person"
             "  AND outremer_id=e.outremer_id AND client_id=e.client_id)")
        args: tuple = ()
        if doc_id:
            q += " AND doc_id=?"
            args = (doc_id,)
        with self._lock:
            rows = self._conn.execute(q + " ORDER BY id", args).fetchall()
        return self._rows(rows)

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
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
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
                self._send(200, {"status": "ok", "writes": "token" if token else "open",
                                 **store.stats()})
            elif path == "/events":
                self._send(200, store.events(params.get("since") or None,
                                             params.get("include_flags") == "1"))
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

        def _write(self, action):
            if self.path.partition("?")[0] != "/decisions":
                self._send(404, {"error": "not found"})
                return
            if token and self.headers.get("X-Review-Token") != token:
                self._send(401, {"error": "missing or wrong X-Review-Token"})
                return
            try:
                length = min(int(self.headers.get("Content-Length", 0)), _MAX_BODY)
                ev = json.loads(self.rfile.read(length) or b"{}")
                self._send(201, action(ev))
            except (ValueError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)})

        def do_POST(self):
            self._write(store.append)

        def do_DELETE(self):
            # Append-only: a withdrawal is recorded, nothing is removed.
            self._write(store.withdraw)

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
