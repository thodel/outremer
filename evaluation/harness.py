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
import shlex
import subprocess
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

# Below this lift over the null linker, a system's agreement figure is not
# evidence that it works — it is evidence that the gold is reject-dominated.
WEAK_SIGNAL_LIFT = 0.05


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
    seg_gold: dict[str, list[int]] | None = None,
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

    gold = seg_gold or {}
    entry = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "combined_agreement": aggregate,
        "segments": {
            seg: {
                "pairs": t,
                "good": g,
                # null = what a linker proposing nothing scores on this gold;
                # lift is the only part that evidences the linker works (#42)
                **(
                    {
                        "accepts": gold[seg][0],
                        "rejects": gold[seg][1],
                        "null": round(gold[seg][1] / t, 4) if t else None,
                        "lift": round(g / t - gold[seg][1] / t, 4) if t else None,
                    }
                    if seg in gold
                    else {}
                ),
            }
            for seg, (t, g) in seg_totals.items()
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
        "--repeat",
        type=int,
        default=1,
        help="evaluate N samples and report mean plus observed range",
    )
    ap.add_argument(
        "--repeat-command",
        default=None,
        help="command to refresh live predictions before every repeated sample",
    )
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
        "--min-lift",
        type=float,
        default=None,
        help="exit 1 if agreement minus the null-linker baseline falls below "
        "this value. Prefer this over --min-agreement: on reject-dominated "
        "gold a do-nothing linker already scores ~0.90, so an absolute "
        "threshold below that can never fail (M9.x / issue #42).",
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

    if args.repeat < 1:
        ap.error("--repeat must be at least 1")
    if args.repeat_command and not args.live:
        ap.error("--repeat-command requires --live")

    samples: list[dict] = []
    for sample_number in range(1, args.repeat + 1):
        if args.repeat_command:
            subprocess.run(shlex.split(args.repeat_command), check=True)
        doc_results: dict[str, dict] = {}
        for f in fixture_files:
            fixture = json.loads(f.read_text())
            doc_results[fixture["doc_id"]] = evaluate_fixture(
                fixture, live=args.live, relink=args.relink
            )

        sample_totals: dict[str, list[int]] = {
            "linking": [0, 0], "wikidata": [0, 0]
        }
        # accepts/rejects per segment, for the null-linker reference
        sample_gold: dict[str, list[int]] = {"linking": [0, 0], "wikidata": [0, 0]}
        for res in doc_results.values():
            for segment in ("linking", "wikidata"):
                result = res.get(segment)
                if result:
                    sample_totals[segment][0] += result["reviewed_pairs"]
                    sample_totals[segment][1] += (
                        result["accept_hit"] + result["reject_avoided"]
                    )
                    sample_gold[segment][0] += (
                        result["accept_hit"] + result["accept_miss"]
                    )
                    sample_gold[segment][1] += (
                        result["reject_hit"] + result["reject_avoided"]
                    )
        sample_pairs = sum(total for total, _ in sample_totals.values())
        sample_good = sum(good for _, good in sample_totals.values())
        samples.append({
            "sample": sample_number,
            "documents": doc_results,
            "segments": sample_totals,
            "gold": sample_gold,
            "aggregate_agreement": (
                sample_good / sample_pairs if sample_pairs else None
            ),
        })

    doc_results = samples[-1]["documents"]

    print(format_report(doc_results))

    # Aggregate agreement across documents (pair-weighted), per system and
    # combined — each adjudicated pair judged against the system that made it
    seg_totals = samples[-1]["segments"]

    seg_gold = samples[-1]["gold"]

    total_pairs = sum(t for t, _ in seg_totals.values())
    good = sum(g for _, g in seg_totals.values())
    # A "null linker" proposes nothing: it misses every accept but avoids
    # every reject, so it scores rejects/total. Reporting it keeps a
    # reject-dominated gold from flattering a linker that does nothing.
    null_good = sum(rej for _, rej in seg_gold.values())
    null_aggregate = (null_good / total_pairs) if total_pairs else None
    print()
    seg_lifts: dict[str, float] = {}
    for seg, label in (("linking", "authority linking"), ("wikidata", "wikidata reconciliation")):
        t, g = seg_totals[seg]
        if t:
            acc, rej = seg_gold[seg]
            null_seg = rej / t
            seg_lifts[seg] = g / t - null_seg
            print(
                f"{label:>24}: {g/t:.4f} over {t} pairs "
                f"(null {null_seg:.4f}, lift {seg_lifts[seg]:+.4f}; "
                f"{acc} accepts / {rej} rejects)"
            )
    # A segment whose lift is near zero carries no positive signal, however
    # healthy the combined figure looks — combining a reject-dominated system
    # with an accept-only one hides exactly that (authority vs wikidata, #42).
    for seg, lift_seg in seg_lifts.items():
        if lift_seg < WEAK_SIGNAL_LIFT:
            print(
                f"::warning::{seg} lift {lift_seg:+.4f} is below "
                f"{WEAK_SIGNAL_LIFT} — this system scores about what a linker "
                f"proposing nothing would score; grow positive gold before "
                f"trusting its agreement figure"
            )
    if total_pairs:
        aggregate = good / total_pairs
        lift = aggregate - null_aggregate
        print(f"{'combined agreement':>24}: {aggregate:.4f} over {total_pairs} reviewed pairs")
        print(f"{'null-linker baseline':>24}: {null_aggregate:.4f} (a linker proposing nothing)")
        print(f"{'lift over null':>24}: {lift:+.4f}  ← the actual signal")
        if lift <= 0:
            print(
                "::warning::linking scores at or below a linker that proposes "
                "nothing — the agreement figure carries no positive signal"
            )
    else:
        aggregate = None
        lift = None
    observed = [
        sample["aggregate_agreement"]
        for sample in samples
        if sample["aggregate_agreement"] is not None
    ]
    uncertainty = None
    if observed:
        uncertainty = {
            "samples": len(observed),
            "mean": sum(observed) / len(observed),
            "min": min(observed),
            "max": max(observed),
        }
        if args.repeat > 1:
            print(
                f"{'observed band':>24}: mean {uncertainty['mean']:.4f}; "
                f"range {uncertainty['min']:.4f}–{uncertainty['max']:.4f} "
                f"over {uncertainty['samples']} samples"
            )

    if args.output:
        Path(args.output).write_text(
            json.dumps(
                {
                    "documents": doc_results,
                    "aggregate_agreement": aggregate,
                    "uncertainty": uncertainty,
                    "samples": samples if args.repeat > 1 else None,
                },
                indent=2,
                ensure_ascii=False,
            )
        )

    if args.append_history:
        _append_history(
            Path(args.append_history), doc_results, aggregate, seg_totals, seg_gold
        )

    failed = False
    if (
        args.min_agreement is not None
        and observed
        and min(observed) < args.min_agreement
    ):
        print(
            f"FAIL: lower observed agreement {min(observed):.4f} "
            f"< --min-agreement {args.min_agreement}",
            file=sys.stderr,
        )
        failed = True

    # Gate on the WEAKEST segment, not the combined figure: authority linking
    # could collapse to proposing nothing and combined agreement would still
    # read 0.90, because wikidata's accept-only gold carries it.
    if args.min_lift is not None and seg_lifts:
        worst_seg = min(seg_lifts, key=lambda s: seg_lifts[s])
        if seg_lifts[worst_seg] < args.min_lift:
            print(
                f"FAIL: {worst_seg} lift {seg_lifts[worst_seg]:+.4f} "
                f"< --min-lift {args.min_lift} "
                f"(combined agreement {aggregate:.4f} hides this)",
                file=sys.stderr,
            )
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
