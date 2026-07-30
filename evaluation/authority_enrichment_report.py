"""Reproducible before/after report for Epic 19 authority enrichment."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evaluation._pipeline import REPO_ROOT, load_authority_lookup, relink
from evaluation.diagnose import diagnose_document
from evaluation.metrics import (
    DEFAULT_FUZZY_THRESHOLD,
    _fuzzy_equal,
    linking_agreement,
    split_pairs_by_system,
)
from evaluation.sweep import sweep
from scripts.linker import normalise

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _top_id(link: dict) -> str | None:
    top = link.get("top_candidate") or {}
    return top.get("outremer_id") or top.get("authority_id")


def _score_bin(score: float) -> str:
    lower = int(score * 20) / 20
    if lower >= 1:
        return "[1.00]"
    return f"[{lower:.2f},{lower + 0.05:.2f})"


def build_report(fixtures_dir: Path = FIXTURES) -> dict:
    lookup = load_authority_lookup()
    authority_source = json.loads(
        (REPO_ROOT / "scripts" / "outremer_index.json").read_text(encoding="utf-8")
    )
    authority = {
        item["authority_id"]: item for item in authority_source.get("persons", [])
    }
    totals = Counter()
    causes = Counter()
    correct_scores: list[float] = []
    accepted_pair_audit: list[dict] = []

    for path in sorted(fixtures_dir.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        predictions = fixture.get("predictions") or {}
        persons = predictions.get("persons") or []
        accepted, _ = split_pairs_by_system(
            [tuple(item) for item in fixture.get("accepted", [])]
        )
        rejected, _ = split_pairs_by_system(
            [tuple(item) for item in fixture.get("rejected", [])]
        )
        for mention, authority_id in accepted:
            record = authority.get(authority_id)
            attested_names = (
                [record.get("preferred_label", ""), *(record.get("variants") or [])]
                if record
                else []
            )
            exact_attestation = any(
                normalise(name) == normalise(mention) for name in attested_names if name
            )
            accepted_pair_audit.append(
                {
                    "document": fixture["doc_id"],
                    "mention": mention,
                    "authority_id": authority_id,
                    "authority_label": record.get("preferred_label") if record else None,
                    "exact_attested_variant": exact_attestation,
                    "status": "attested" if exact_attestation else "needs_scholarly_review",
                }
            )
        if not persons or not (accepted or rejected):
            continue

        links = relink(persons, lookup)
        metrics = linking_agreement(links, accepted, rejected)
        totals.update(metrics)
        rows = diagnose_document(fixture["doc_id"], accepted, persons, links)
        causes.update(row["cause"] for row in rows)

        for mention, accepted_id in accepted:
            for link in links:
                if (
                    _fuzzy_equal(link.get("person", ""), mention, DEFAULT_FUZZY_THRESHOLD)
                    and _top_id(link) == accepted_id
                ):
                    correct_scores.append(float(link.get("confidence") or 0))
                    break

    reviewed = totals["reviewed_pairs"]
    good = totals["accept_hit"] + totals["reject_avoided"]
    bins = Counter(_score_bin(score) for score in correct_scores)
    return {
        "authority": {
            "agreement": round(good / reviewed, 4) if reviewed else 0.0,
            "reviewed_pairs": reviewed,
            "accept_hit": totals["accept_hit"],
            "accept_miss": totals["accept_miss"],
            "reject_hit": totals["reject_hit"],
            "reject_avoided": totals["reject_avoided"],
        },
        "accepted_pair_diagnosis": dict(sorted(causes.items())),
        "accepted_authority_pair_audit": sorted(
            accepted_pair_audit, key=lambda row: (row["document"], row["mention"])
        ),
        "correct_match_score_distribution": dict(sorted(bins.items())),
        "candidate_floor_sweep": sweep(
            [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85], fixtures_dir
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = build_report(args.fixtures)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
