"""
evaluation/diagnose.py

Classify every accept_miss in the fixture set by cause (issue #42):

    not_extracted     — the accepted mention is absent from the persons list
                        (extraction drift: today's engine no longer finds it)
    no_candidates     — extracted, but the linker proposed nothing
    ranked_below_top  — adjudicated id among candidates, just not the top
    candidate_missing — candidates exist, adjudicated id not among them

The first cause is an extraction problem; the last three are linker
problems (recall, ranking, candidate generation respectively).

Usage (from repo root):
    python -m evaluation.diagnose               # fixture snapshots
    python -m evaluation.diagnose --live        # current site/data
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.metrics import DEFAULT_FUZZY_THRESHOLD, _fuzzy_equal

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _candidate_ids(link: dict) -> list[str]:
    ids = []
    for c in link.get("candidates") or []:
        cid = c.get("outremer_id") or c.get("authority_id")
        if cid:
            ids.append(cid)
    top = link.get("top_candidate") or {}
    tid = top.get("outremer_id") or top.get("authority_id")
    if tid and tid not in ids:
        ids.insert(0, tid)
    return ids


def diagnose_document(
    doc_id: str,
    accepted: list[tuple[str, str]],
    persons: list[str],
    links: list[dict],
    *,
    threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> list[dict]:
    rows = []
    for person, auth_id in accepted:
        person_links = [
            link
            for link in links
            if _fuzzy_equal(link.get("person", ""), person, threshold)
        ]
        top_ids = set()
        all_candidate_ids: set[str] = set()
        for link in person_links:
            ids = _candidate_ids(link)
            all_candidate_ids.update(ids)
            top = link.get("top_candidate") or {}
            tid = top.get("outremer_id") or top.get("authority_id")
            if tid:
                top_ids.add(tid)

        if auth_id in top_ids:
            cause = "HIT"
        elif not any(_fuzzy_equal(p, person, threshold) for p in persons):
            cause = "not_extracted"
        elif not all_candidate_ids:
            cause = "no_candidates"
        elif auth_id in all_candidate_ids:
            cause = "ranked_below_top"
        else:
            cause = "candidate_missing"

        rows.append(
            {
                "doc_id": doc_id,
                "person": person,
                "accepted_id": auth_id,
                "cause": cause,
                "top_ids": sorted(top_ids),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fixtures", default=str(FIXTURES_DIR))
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    all_rows: list[dict] = []
    for f in sorted(Path(args.fixtures).glob("*.json")):
        fx = json.loads(f.read_text())
        # Only authority-system pairs: wikidata pairs are judged by
        # wikidata_agreement against the reconciliation cache, and the
        # causes below are authority-linker-specific (#42).
        accepted = [
            tuple(x) for x in fx.get("accepted", [])
            if not str(x[1]).startswith("wikidata:")
        ]
        if not accepted:
            continue
        if args.live:
            live = json.loads(
                (REPO_ROOT / "site" / "data" / f"{fx['doc_id']}.json").read_text()
            )
            persons = [p.get("name", "") for p in live.get("persons", [])]
            links = live.get("links", [])
        else:
            preds = fx.get("predictions") or {}
            persons = preds.get("persons", [])
            links = preds.get("links", [])
        all_rows.extend(diagnose_document(fx["doc_id"], accepted, persons, links))

    by_cause: dict[str, int] = {}
    for r in all_rows:
        by_cause[r["cause"]] = by_cause.get(r["cause"], 0) + 1

    for r in all_rows:
        if r["cause"] != "HIT":
            print(
                f"{r['doc_id'][:36]:<36} {r['person'][:28]:<28} "
                f"{r['accepted_id']:<12} {r['cause']}"
            )
    print("\ncause breakdown:", json.dumps(by_cause, indent=2))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(all_rows, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
