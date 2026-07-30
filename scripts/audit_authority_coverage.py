#!/usr/bin/env python3
"""Audit the authority file against a sourced, multilingual benchmark list."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from linker import normalise

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHORITY = ROOT / "scripts" / "outremer_index.json"
DEFAULT_BENCHMARK = ROOT / "data" / "audits" / "epic19-benchmark-figures.json"
DEFAULT_OUTPUT = ROOT / "data" / "audits" / "epic19-coverage-report.json"


def audit(authority_path: Path, benchmark_path: Path) -> dict:
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    names: dict[str, str] = {}
    for record in authority.get("persons", []):
        for name in [record.get("preferred_label"), *(record.get("variants") or [])]:
            if name:
                names.setdefault(normalise(name), record["authority_id"])

    rows = []
    for figure in benchmark.get("figures", []):
        candidate_names = [
            figure["preferred_label"],
            *(figure.get("variants") or []),
        ]
        matched_id = next(
            (names[normalise(name)] for name in candidate_names if normalise(name) in names),
            None,
        )
        rows.append(
            {
                **figure,
                "status": "present" if matched_id else "missing",
                "authority_id": matched_id,
            }
        )

    by_tradition = {}
    for tradition in sorted({row["tradition"] for row in rows}):
        subset = [row for row in rows if row["tradition"] == tradition]
        by_tradition[tradition] = {
            "total": len(subset),
            "present": sum(row["status"] == "present" for row in subset),
            "missing": sum(row["status"] == "missing" for row in subset),
        }
    statuses = Counter(row["status"] for row in rows)
    return {
        "schema_version": 1,
        "authority_records": len(authority.get("persons", [])),
        "benchmark_figures": len(rows),
        "summary": dict(sorted(statuses.items())),
        "by_tradition": by_tradition,
        "figures": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority", type=Path, default=DEFAULT_AUTHORITY)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = audit(args.authority, args.benchmark)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{report['summary'].get('present', 0)} present; "
        f"{report['summary'].get('missing', 0)} missing"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
