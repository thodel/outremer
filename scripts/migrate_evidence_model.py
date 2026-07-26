#!/usr/bin/env python3
"""Read-only migration inventory for the evidence-first v1 contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def count_records(path: Path) -> int:
    if not path.exists():
        return 0
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("persons", "records", "objects"):
            if isinstance(value.get(key), list):
                return len(value[key])
        return len(value)
    return 0


def dry_run(root: Path = ROOT) -> dict:
    decisions = root / "data" / "decisions.json"
    before = file_sha256(decisions)
    inputs = {
        "authority": root / "scripts" / "outremer_index.json",
        "wikidata": root / "site" / "data" / "wikidata_matches.json",
        "extractions": root / "site" / "index.json",
        "dhi_quarantine": root / "data" / "dhi" / "dhi_sample_output.json",
        "fmg_quarantine": root / "data" / "fmg" / "fmg_medlands_crusaders.json",
    }
    mappings = {
        name: {
            "path": path.relative_to(root).as_posix(),
            "records": count_records(path),
            "target_objects": [
                "source_work", "manifestation", "snapshot", "passage", "mention",
                "assertion", "identity_hypothesis",
            ],
            "quarantined": "quarantine" in name,
        }
        for name, path in inputs.items()
    }
    after = file_sha256(decisions)
    return {
        "mode": "dry-run",
        "schema_version": "1.0.0",
        "mappings": mappings,
        "decisions_sha256_before": before,
        "decisions_sha256_after": after,
        "decisions_unchanged": before == after,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = dry_run()
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
