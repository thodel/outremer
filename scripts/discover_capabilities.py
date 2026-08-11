#!/usr/bin/env python3
"""Discover configured shared capabilities and emit a secret-free report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from capabilities.adapters import default_registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--invocation-log", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    registry = default_registry(args.invocation_log)
    report = registry.discover()
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 1 if args.require_ready and report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
