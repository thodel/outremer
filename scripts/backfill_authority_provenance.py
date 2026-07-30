#!/usr/bin/env python3
"""Backfill and validate per-name-form provenance in the authority index."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "scripts" / "outremer_index.json"


def _sources(record: dict) -> list[dict[str, str]]:
    provenance = record.get("provenance") or {}
    system = str(provenance.get("source_system") or "").strip()
    sources = [
        {"system": system, "locator": str(path)}
        for path in provenance.get("source_files") or []
        if system and path
    ]
    if not sources and system == "manual":
        note = str(provenance.get("note") or "")
        issue = re.search(r"issue\s+#(\d+)", note, flags=re.IGNORECASE)
        if issue:
            sources.append({"system": "github-issue", "locator": f"issue:{issue.group(1)}"})
    return sources


def backfill(index: dict) -> dict:
    for record in index.get("persons", []):
        sources = _sources(record)
        if not sources:
            raise ValueError(f"{record.get('authority_id')}: no attributable source")
        names = [record.get("preferred_label"), *(record.get("variants") or [])]
        record["variant_provenance"] = {
            name: [dict(source) for source in sources] for name in names if name
        }
    return index


def validate(index: dict) -> list[str]:
    errors = []
    for record in index.get("persons", []):
        provenance = record.get("variant_provenance") or {}
        names = {record.get("preferred_label"), *(record.get("variants") or [])}
        names.discard(None)
        if set(provenance) != names:
            errors.append(f"{record.get('authority_id')}: name/provenance coverage differs")
        for name, sources in provenance.items():
            if not sources or any(
                not source.get("system") or not source.get("locator") for source in sources
            ):
                errors.append(
                    f"{record.get('authority_id')} {name!r}: incomplete provenance"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path, nargs="?", default=DEFAULT_INDEX)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    data = json.loads(args.index.read_text(encoding="utf-8"))
    if not args.check:
        backfill(data)
        args.index.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    errors = validate(data)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"{len(data.get('persons', []))} authority records have per-variant provenance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
