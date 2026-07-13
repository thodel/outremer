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
    """Load current pipeline output for a doc from site/data/.

    Includes the wikidata reconciliation entries for the doc — without
    them, live wikidata agreement reads as all-miss (caught by the first
    CI history entry, 2026-07-12).
    """
    path = REPO_ROOT / "site" / "data" / f"{doc_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"--live requested but {path} does not exist; run the pipeline first"
        )
    data = json.loads(path.read_text())
    wikidata: dict = {}
    wm_path = REPO_ROOT / "site" / "data" / "wikidata_matches.json"
    if wm_path.exists():
        wikidata = (json.loads(wm_path.read_text()).get(doc_id)) or {}
    return {
        "persons": [p.get("name", "") for p in data.get("persons", [])],
        "links": data.get("links", []),
        "wikidata": wikidata,
    }


def evaluate_fixture(fixture: dict, *, live: bool = False, relink: bool = False) -> dict:
    """Evaluate one fixture; returns {mode, extraction?, linking?, wikidata?}.

    ``relink`` recomputes authority links from the snapshot's extracted
    persons with the *current* linker code — the measurement mode for
    linker changes (extraction held constant, no LLM needed).
    """
    doc_id = fixture["doc_id"]
    mode = fixture.get("mode", "adjudicated")
    preds = (
        load_predictions_live(doc_id) if live else fixture.get("predictions") or {}
    )
    if relink and preds.get("persons"):
        from evaluation._pipeline import load_authority_lookup
        from evaluation._pipeline import relink as _relink

        preds = dict(preds)
        preds["links"] = _relink(preds["persons"], load_authority_lookup())

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


def _append_history(
    path: Path,
    doc_results: dict[str, dict],
    aggregate: float | None,
    seg_totals: dict[str, list[int]],
) -> None:
    """Append one eval-history entry (M9.4) and warn on a noise jump (M9.3).

    Extraction noise comes from the latest pipeline run report if present;
    the >10-point jump check compares against the previous history entry and
    emits a GitHub Actions ::warning:: (never a failure).
    """
    from datetime import datetime, timezone

    noise_share = None
    report_path = REPO_ROOT / "data" / "staging" / "run_report.json"
    if report_path.exists():
        noise = (json.loads(report_path.read_text()).get("noise")) or {}
        noise_share = noise.get("noise_share")

    prev = None
    if path.exists():
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        if lines:
            prev = json.loads(lines[-1])

    entry = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "combined_agreement": aggregate,
        "segments": {
            seg: {"pairs": t, "good": g} for seg, (t, g) in seg_totals.items()
        },
        "per_document": {
            doc: {
                k: v.get("agreement")
                for k, v in res.items()
                if isinstance(v, dict) and "agreement" in v
            }
            for doc, res in doc_results.items()
        },
        "noise_share": noise_share,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if (
        noise_share is not None
        and prev is not None
        and prev.get("noise_share") is not None
        and noise_share - prev["noise_share"] > 0.10
    ):
        print(
            f"::warning::extraction noise share jumped "
            f"{prev['noise_share']:.2f} → {noise_share:.2f} (>10 points)"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fixtures", default=str(FIXTURES_DIR))
    ap.add_argument(
        "--live",
        action="store_true",
        help="evaluate current site/data output instead of fixture snapshots",
    )
    ap.add_argument(
        "--relink",
        action="store_true",
        help="recompute authority links from snapshot persons with the "
        "current linker code (measures linker changes, M10.x)",
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
    ap.add_argument(
        "--append-history",
        default=None,
        metavar="JSONL",
        help="append this run's results to a JSONL history file (M9.4); "
        "warns when extraction noise jumps >10 points vs the previous entry",
    )
    args = ap.parse_args(argv)

    fixture_files = sorted(Path(args.fixtures).glob("*.json"))
    if not fixture_files:
        print(f"No fixtures found in {args.fixtures}", file=sys.stderr)
        return 2

    doc_results: dict[str, dict] = {}
    for f in fixture_files:
        fixture = json.loads(f.read_text())
        doc_results[fixture["doc_id"]] = evaluate_fixture(
            fixture, live=args.live, relink=args.relink
        )

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

    if args.append_history:
        _append_history(Path(args.append_history), doc_results, aggregate, seg_totals)

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
