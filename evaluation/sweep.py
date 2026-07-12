"""
evaluation/sweep.py

Threshold sweep for the authority linker (M10.3): re-links fixture
snapshots at a range of candidate floors and reports agreement,
accept_hit, and reject_hit per floor, so the operating point is a
data-backed choice instead of an inherited guess.

The high/medium bars only affect status labels on the site, not which
top candidate is proposed — the floor is the axis that moves agreement.

Usage (from repo root):
    python -m evaluation.sweep
    python -m evaluation.sweep --floors 0.60 0.65 0.70 0.75 0.80
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation._pipeline import load_authority_lookup, relink
from evaluation.metrics import linking_agreement, split_pairs_by_system

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def sweep(floors: list[float], fixtures_dir: Path = FIXTURES_DIR) -> list[dict]:
    lookup = load_authority_lookup()
    docs = []
    for f in sorted(fixtures_dir.glob("*.json")):
        fx = json.loads(f.read_text())
        preds = fx.get("predictions") or {}
        acc, _ = split_pairs_by_system([tuple(x) for x in fx.get("accepted", [])])
        rej, _ = split_pairs_by_system([tuple(x) for x in fx.get("rejected", [])])
        if (acc or rej) and preds.get("persons"):
            docs.append((preds["persons"], acc, rej))

    rows = []
    for floor in floors:
        totals = {"reviewed_pairs": 0, "accept_hit": 0, "accept_miss": 0,
                  "reject_hit": 0, "reject_avoided": 0}
        for persons, acc, rej in docs:
            links = relink(persons, lookup, min_score=floor)
            res = linking_agreement(links, acc, rej)
            for k in totals:
                totals[k] += res[k]
        good = totals["accept_hit"] + totals["reject_avoided"]
        rows.append({
            "floor": floor,
            "agreement": round(good / totals["reviewed_pairs"], 4)
            if totals["reviewed_pairs"] else 0.0,
            **totals,
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--floors", nargs="+", type=float,
                    default=[0.60, 0.65, 0.70, 0.75, 0.80, 0.85])
    args = ap.parse_args(argv)

    rows = sweep(args.floors)
    print(f"{'floor':>6} {'agree':>7} {'acc_hit':>8} {'acc_miss':>9} "
          f"{'rej_hit':>8} {'rej_avoid':>10}")
    for r in rows:
        print(f"{r['floor']:>6.2f} {r['agreement']:>7.4f} {r['accept_hit']:>8} "
              f"{r['accept_miss']:>9} {r['reject_hit']:>8} {r['reject_avoided']:>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
