#!/usr/bin/env python3
"""Run safe discovery probes against the configured shared capability stack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from capabilities.adapters import default_registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require",
        default="gpustack,atr,mcp,qlever,voyant",
        help="comma-separated capability ids that must report available",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = default_registry().discover()
    by_id = {item["capability_id"]: item for item in report["capabilities"]}
    required = {item.strip() for item in args.require.split(",") if item.strip()}
    errors = [
        f"{cap_id}: {by_id.get(cap_id, {}).get('status', 'missing')}"
        for cap_id in sorted(required)
        if by_id.get(cap_id, {}).get("status") != "available"
    ]
    result = {**report, "smoke_required": sorted(required), "smoke_errors": errors}
    result["status"] = "pass" if not errors else "fail"
    content = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
