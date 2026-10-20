#!/usr/bin/env python3
"""Carry adjudications from the review API into data/decisions.json (M13.3, #179).

The nightly runs this before the pipeline. It asks the review API for every
event after the newest timestamp already in the file, appends the new ones
(append-only: nothing in the file is rewritten or removed), validates the
result with the same rules the pipeline applies, and only then writes. The
nightly commits the file together with the rebuilt fixtures, so each
imported decision is a line in a diff with reviewer pseudonym and time.

Exit codes: 0 — nothing new, or the file was updated (stdout says which);
1 — the API was unreachable or the merged file failed validation (the file
is left exactly as it was). The nightly treats 1 as a warning, not a stop:
one unreachable API must not cost a night's extraction.

Usage:
    python scripts/import_review_decisions.py [--url http://127.0.0.1:8089]
        [--decisions data/decisions.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_decisions import validate_decisions_file  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = os.environ.get("REVIEW_API_URL", "http://127.0.0.1:8089")
# What makes two records the same decision: the API never emits two events
# with the same reviewer, pair and timestamp.
IDENTITY = ("doc_id", "person", "outremer_id", "client_id", "submitted_at")
# The fields the file carries; the API's own `id` is not part of the record.
FIELDS = ("doc_id", "person", "outremer_id", "decision", "comment",
          "client_id", "scholar_name", "submitted_at", "supersedes")


def identity(d: dict) -> tuple:
    return tuple(" ".join(str(d.get(k) or "").split()) for k in IDENTITY)


def fetch_events(url: str, since: str | None, timeout: float = 20.0) -> list[dict]:
    query = urllib.parse.urlencode({"since": since}) if since else ""
    full = f"{url.rstrip('/')}/events" + (f"?{query}" if query else "")
    with urllib.request.urlopen(full, timeout=timeout) as resp:  # noqa: S310 — loopback API
        payload = json.loads(resp.read())
    if not isinstance(payload, list):
        raise ValueError(f"{full}: expected a list, got {type(payload).__name__}")
    return payload


def as_record(ev: dict) -> dict:
    rec = {k: ev.get(k) for k in FIELDS if k in ev}
    rec["comment"] = rec.get("comment") or ""
    if not rec.get("supersedes"):
        rec.pop("supersedes", None)
    rec["source"] = "review_api"
    return rec


def merge(existing: list[dict], events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (merged, added). Order: file order, then new events in API order."""
    seen = {identity(d) for d in existing}
    added = []
    for ev in events:
        rec = as_record(ev)
        key = identity(rec)
        if key in seen:
            continue
        seen.add(key)
        added.append(rec)
    return existing + added, added


def newest_timestamp(existing: list[dict]) -> str | None:
    stamps = [str(d.get("submitted_at") or "") for d in existing if d.get("source") == "review_api"]
    return max(stamps) if stamps else None


def summarise(added: list[dict]) -> str:
    by_decision = Counter(d.get("decision") for d in added)
    by_reviewer = Counter(d.get("scholar_name") or d.get("client_id") for d in added)
    return (f"{len(added)} new decision(s): "
            + ", ".join(f"{n} {k}" for k, n in sorted(by_decision.items()))
            + " — from " + ", ".join(f"{who} ({n})" for who, n in by_reviewer.most_common()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default=DEFAULT_URL, help="review API base (default: %(default)s)")
    ap.add_argument("--decisions", default=str(REPO_ROOT / "data" / "decisions.json"))
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    ap.add_argument("--full", action="store_true",
                    help="ask for the whole log, not only events after the newest imported one")
    args = ap.parse_args(argv)

    path = Path(args.decisions)
    existing = json.loads(path.read_text()) if path.exists() else []
    if not isinstance(existing, list):
        print(f"ERROR: {path} is not a list", file=sys.stderr)
        return 1

    since = None if args.full else newest_timestamp(existing)
    try:
        events = fetch_events(args.url, since)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"ERROR: review API {args.url} unreachable: {exc}", file=sys.stderr)
        return 1

    merged, added = merge(existing, events)
    if not added:
        print(f"review import: nothing new ({len(events)} event(s) seen, {len(existing)} in file)")
        return 0

    # Validate the merged file exactly as the pipeline would, before writing.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=path.parent) as tmp:
        json.dump(merged, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
    tmp_path = Path(tmp.name)
    try:
        result = validate_decisions_file(tmp_path)
        if result.errors:
            print(f"ERROR: merged decisions fail validation ({len(result.errors)} error(s)); "
                  f"{path} left unchanged", file=sys.stderr)
            for e in result.errors[:10]:
                print(f"  [index {e.entry_index}] {e.field}: {e.message}", file=sys.stderr)
            return 1
        print("review import: " + summarise(added))
        for d in added:
            print(f"  + {d['doc_id']} :: {d['person']} :: {d.get('outremer_id') or '-'} "
                  f"→ {d['decision']} ({d.get('scholar_name') or d.get('client_id')}, {d['submitted_at']})")
        if result.conflicts:
            print(f"review import: {len(result.conflicts)} conflict(s) between reviewers "
                  f"(effective_decisions() leaves them to the vote):")
            for c in result.conflicts[:10]:
                print(f"  ! {c.doc_id} :: {c.person} :: {c.id} accepts={c.accepts} rejects={c.rejects}")
        if args.dry_run:
            print("review import: dry run — nothing written")
            return 0
        os.replace(tmp_path, path)
        print(f"review import: wrote {path} ({len(merged)} records)")
        return 0
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
