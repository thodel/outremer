#!/usr/bin/env python3
"""Publish a machine-readable status of the last pipeline run (M20.6, #115).

Writes site/data/status.json from the run report, the release-control gate
result and the evaluation history. The file is committed with the site, so
GitHub Pages serves it — observability without a server: anything (a cron
healthcheck, a dashboard, a colleague's curl) can ask "did last night run,
on which engine, and did the gate pass?" without SSH access to tei.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def build_status(
    run_report_path: Path,
    gate_path: Path | None,
    history_path: Path | None,
) -> dict:
    status: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": None,
        "gate": None,
        "evaluation": None,
    }
    if run_report_path.exists():
        r = json.loads(run_report_path.read_text())
        status["run"] = {
            "run_at": r.get("run_at"),
            "docs_total": r.get("docs_total"),
            "docs_failed": r.get("docs_failed"),
            "total_persons": r.get("total_persons"),
            "llm_provider": r.get("llm_provider"),
            "extraction_model": r.get("extraction_model"),
            "extraction_seed": r.get("extraction_seed"),
            "documents_by_engine": (r.get("extraction") or {}).get("documents_by_engine"),
            "fallback_chunks": ((r.get("extraction") or {}).get("degradation") or {}).get("fallback_chunks"),
            "noise_share": (r.get("noise") or {}).get("noise_share"),
        }
    if gate_path and gate_path.exists():
        g = json.loads(gate_path.read_text())
        status["gate"] = {"status": g.get("status"), "errors": g.get("errors") or []}
    if history_path and history_path.exists():
        lines = [ln for ln in history_path.read_text().splitlines() if ln.strip()]
        if lines:
            h = json.loads(lines[-1])
            status["evaluation"] = {
                "run_at": h.get("run_at"),
                "combined_agreement": h.get("combined_agreement"),
                "segments": h.get("segments"),
            }
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-report", type=Path, default=Path("data/staging/run_report.json"))
    ap.add_argument("--gate", type=Path, default=None)
    ap.add_argument("--history", type=Path, default=Path("data/staging/eval_history.jsonl"))
    ap.add_argument("--output", type=Path, default=Path("site/data/status.json"))
    args = ap.parse_args(argv)
    status = build_status(args.run_report, args.gate, args.history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    print(f"status written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
