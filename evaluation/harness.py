"""
evaluation/harness.py

Run the OUTREMER evaluation over gold fixtures and print/store a report.

Fixture format (one JSON file per document in evaluation/fixtures/):

    {
      "doc_id": "rileysmith-motivesearliestcrusaders-1983-92cc17aaccd3",
      "mode": "adjudicated",            # or "full"
      "gold_persons": ["..."],          # full mode only
      "accepted": [["Miles of Clermont", "AUTH:CR115"]],   # adjudicated mode
      "rejected": [["Miles of Clermont", "AUTH:CR119"]],
      "predictions": {                  # snapshot for offline/CI determinism
        "persons": ["..."],
        "links": [ {"person": "...", "top_candidate": {"authority_id": "..."}} ]
      }
    }

By default predictions come from the fixture snapshot so CI needs no
pipeline run. Pass ``--live`` to evaluate the current ``site/data/`` output
instead — that is the number that tells you whether a prompt/model change
helped.

Usage (from repo root):
    python -m evaluation.harness
    python -m evaluation.harness --live --min-agreement 0.5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evaluation.metrics import (
    extraction_prf,
    format_report,
    linking_agreement,
    split_pairs_by_system,
    wikidata_agreement,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_predictions_live(doc_id: str) -> dict:
    """Load current pipeline output for a doc from site/data/."""
    path = REPO_ROOT / "site" / "data" / f"{doc_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"--live requested but {path} does not exist; run the pipeline first"
        )
    data = json.loads(path.read_text())
    return {
        "persons": [p.get("name", "") for p in data.get("persons", [])],
        "links": data.get("links", []),
    }


def evaluate_fixture(fixture: dict, *, live: bool = False) -> dict:
    """Evaluate one fixture; returns {mode, extraction?, linking?}."""
    doc_id = fixture["doc_id"]
    mode = fixture.get("mode", "adjudicated")
    preds = (
        load_predictions_live(doc_id) if live else fixture.get("predictions") or {}
    )

    result: dict = {"mode": mode}
    if mode == "full" and fixture.get("gold_persons"):
        result["extraction"] = extraction_prf(
            preds.get("persons", []), fixture["gold_persons"]
        )
    accepted = [tuple(x) for x in fixture.get("accepted", [])]
    rejected = [tuple(x) for x in fixture.get("rejected", [])]
    # Scholars adjudicated two systems; judge each against its own (#42)
    acc_auth, acc_wd = split_pairs_by_system(accepted)
    rej_auth, rej_wd = split_pairs_by_system(rejected)
    if acc_auth or rej_auth:
        result["linking"] = linking_agreement(
            preds.get("links", []), acc_auth, rej_auth
        )
    if acc_wd or rej_wd:
        result["wikidata"] = wikidata_agreement(
            preds.get("wikidata") or {}, acc_wd, rej_wd
        )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fixtures", default=str(FIXTURES_DIR))
    ap.add_argument(
        "--live",
        action="store_true",
        help="evaluate current site/data output instead of fixture snapshots",
    )
    ap.add_argument(
        "--output",
        default=None,
        help="write full JSON results to this path",
    )
    ap.add_argument(
        "--min-agreement",
        type=float,
        default=None,
        help="exit 1 if aggregate linking agreement falls below this value",
    )
    args = ap.parse_args(argv)

    fixture_files = sorted(Path(args.fixtures).glob("*.json"))
    if not fixture_files:
        print(f"No fixtures found in {args.fixtures}", file=sys.stderr)
        return 2

    doc_results: dict[str, dict] = {}
    for f in fixture_files:
        fixture = json.loads(f.read_text())
        doc_results[fixture["doc_id"]] = evaluate_fixture(fixture, live=args.live)

    print(format_report(doc_results))

    # Aggregate agreement across documents (pair-weighted), per system and
    # combined — each adjudicated pair judged against the system that made it
    seg_totals: dict[str, list[int]] = {"linking": [0, 0], "wikidata": [0, 0]}
    for res in doc_results.values():
        for seg in ("linking", "wikidata"):
            r = res.get(seg)
            if r:
                seg_totals[seg][0] += r["reviewed_pairs"]
                seg_totals[seg][1] += r["accept_hit"] + r["reject_avoided"]

    total_pairs = sum(t for t, _ in seg_totals.values())
    good = sum(g for _, g in seg_totals.values())
    print()
    for seg, label in (("linking", "authority linking"), ("wikidata", "wikidata reconciliation")):
        t, g = seg_totals[seg]
        if t:
            print(f"{label:>24}: {g/t:.4f} over {t} pairs")
    if total_pairs:
        aggregate = good / total_pairs
        print(f"{'combined agreement':>24}: {aggregate:.4f} over {total_pairs} reviewed pairs")
    else:
        aggregate = None

    if args.output:
        Path(args.output).write_text(
            json.dumps(
                {"documents": doc_results, "aggregate_agreement": aggregate},
                indent=2,
                ensure_ascii=False,
            )
        )

    if (
        args.min_agreement is not None
        and aggregate is not None
        and aggregate < args.min_agreement
    ):
        print(
            f"FAIL: aggregate agreement {aggregate:.4f} < --min-agreement {args.min_agreement}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
