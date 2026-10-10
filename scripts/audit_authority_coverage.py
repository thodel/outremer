#!/usr/bin/env python3
"""Audit the authority file against sourced benchmark lists (#92).

    python scripts/audit_authority_coverage.py                 # the #99 list
    python scripts/audit_authority_coverage.py --benchmark data/audits/benchmarks/*.json

A figure is **present by QID** when a record asserts its Wikidata QID (exact),
**hypothesised** when a record lists it among its QID candidates, **present by
name** when its label or a variant equals a recorded name form — single-word
names excluded, "Robert" matches everyone — and **missing** otherwise. The report
gives the counts per list and, where the list says so, per tradition.
"""
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


def _single_word(name: str) -> bool:
    return len(normalise(name).split()) < 2


def _indexes(authority: dict) -> tuple[dict, dict, dict]:
    by_qid: dict[str, str] = {}
    by_candidate: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for record in authority.get("persons", []):
        ids = record.get("identifiers") or {}
        if ids.get("wikidata_qid"):
            by_qid.setdefault(ids["wikidata_qid"], record["authority_id"])
        for c in ids.get("wikidata_candidates") or []:
            by_candidate.setdefault(c.get("qid"), record["authority_id"])
        for name in [record.get("preferred_label"), *(record.get("variants") or [])]:
            if name and not _single_word(name):
                by_name.setdefault(normalise(name), record["authority_id"])
    return by_qid, by_candidate, by_name


def audit_list(authority: dict, benchmark: dict) -> dict:
    by_qid, by_candidate, by_name = _indexes(authority)
    rows = []
    for figure in benchmark.get("figures", []):
        qid = figure.get("wikidata")
        names = [figure["preferred_label"], *(figure.get("variants") or [])]
        status, matched = "missing", None
        if qid and qid in by_qid:
            status, matched = "present", by_qid[qid]
        elif qid and qid in by_candidate:
            status, matched = "hypothesised", by_candidate[qid]
        else:
            hit = next((by_name[normalise(n)] for n in names
                        if n and not _single_word(n) and normalise(n) in by_name), None)
            if hit:
                status, matched = "present_by_name", hit
        rows.append({**figure, "status": status, "authority_id": matched})
    statuses = Counter(row["status"] for row in rows)
    report = {
        "id": benchmark.get("id", "benchmark"),
        "source": benchmark.get("source", "manual"),
        "licence": benchmark.get("licence"),
        "scope": benchmark.get("scope"),
        "fetched_at": benchmark.get("fetched_at"),
        "benchmark_figures": len(rows),
        "summary": dict(sorted(statuses.items())),
        "figures": rows,
    }
    if any("tradition" in row for row in rows):
        by_tradition = {}
        for tradition in sorted({row.get("tradition", "?") for row in rows}):
            subset = [row for row in rows if row.get("tradition", "?") == tradition]
            by_tradition[tradition] = {
                "total": len(subset),
                "present": sum(row["status"] in ("present", "present_by_name") for row in subset),
                "missing": sum(row["status"] == "missing" for row in subset),
            }
        report["by_tradition"] = by_tradition
    return report


def audit(authority_path: Path, benchmark_path: Path) -> dict:
    """One list, in the shape the #99 report had (kept for its consumers)."""
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    report = audit_list(authority, benchmark)
    summary = Counter()
    for row in report["figures"]:
        summary["present" if row["status"] in ("present", "present_by_name") else row["status"]] += 1
    return {
        "schema_version": 1,
        "authority_records": len(authority.get("persons", [])),
        "benchmark_figures": report["benchmark_figures"],
        "summary": dict(sorted(summary.items())),
        "by_tradition": report.get("by_tradition", {}),
        "figures": report["figures"],
    }


def audit_many(authority_path: Path, benchmark_paths: list[Path]) -> dict:
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    lists = [audit_list(authority, json.loads(p.read_text(encoding="utf-8"))) for p in benchmark_paths]
    return {
        "schema_version": 2,
        "authority_records": len(authority.get("persons", [])),
        "lists": lists,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--authority", type=Path, default=DEFAULT_AUTHORITY)
    parser.add_argument("--benchmark", type=Path, nargs="*", default=[DEFAULT_BENCHMARK])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if len(args.benchmark) == 1 and args.benchmark[0] == DEFAULT_BENCHMARK:
        report = audit(args.authority, args.benchmark[0])
        print(f"{report['summary'].get('present', 0)} present; "
              f"{report['summary'].get('missing', 0)} missing")
    else:
        report = audit_many(args.authority, args.benchmark)
        for item in report["lists"]:
            s = item["summary"]
            print(f"  {item['id']:<32} {item['benchmark_figures']:>4} figures | "
                  f"by QID {s.get('present', 0):>3} | hypothesised {s.get('hypothesised', 0):>2} | "
                  f"by name {s.get('present_by_name', 0):>2} | missing {s.get('missing', 0):>3}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
