#!/usr/bin/env python3
"""
M17.3 Air-gap test — assert the pipeline succeeds with egress blocked.

Usage:
    python scripts/airgap_test.py [--subset] [--verbose]

Options
───────
    --subset   run only the smallest fixture (Hamblin) instead of data/raw
    --verbose  print full run output instead of a one-line verdict

What it tests
─────────────
1. The pipeline completes end-to-end without reaching any host except the
   configured inference services (see scripts/airgap.py and the README
   section "Permitted network hosts").
2. The output documents are non-empty: the run did not silently fall back
   to empty text or empty candidate lists.

How the block works
───────────────────
The pipeline runs as ``run_pipeline.py --airgap``: the child installs the
guard from scripts/airgap.py in its own process before any network I/O and
exports OUTREMER_AIRGAP=1, so the Wikidata reconciliation it starts as a
further subprocess installs the same guard.  A patch in this parent process
would reach neither of them.

Live-backend note
─────────────────
The run needs GPUStack (and the ATR gateway, when configured) to be
reachable, with or without --subset: --subset only shrinks the corpus.  CI
runs tests/test_airgap.py (offline); the tei nightly runs the whole pipeline
under the same guard every night (deploy/tei/nightly.sh).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import airgap  # noqa: E402

SUBSET_SOURCES = ["Hamblin-MuslimPerspectivesMilitary-2001.pdf"]


def _child_command(args: list[str]) -> list[str]:
    """The pipeline, started with its own egress guard."""
    return [sys.executable, str(REPO_ROOT / "scripts" / "run_pipeline.py"), "--airgap", *args]


def run_airgap_test(*, subset: bool = False, verbose: bool = False) -> dict:
    """Run the pipeline with egress blocked; return a verdict dict."""
    tmp = Path(tempfile.mkdtemp(prefix="airgap_test_"))
    bib = tmp / "bib"
    bib.mkdir()
    out_dir = tmp / "site"
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True)

    raw = REPO_ROOT / "data" / "raw"
    args = ["--input-dir", str(raw), "--site-dir", str(out_dir),
            "--bib-dir", str(bib), "--llm-metadata"]
    if subset:
        for name in SUBSET_SOURCES:
            args += ["--file", str(raw / name)]

    verdict: dict = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "subset": subset,
        "passed": False,
        "docs_ok": 0,
        "docs_total": 0,
        "docs_failed": 0,
        "failures": [],
        "permitted_hosts": sorted(airgap.permitted_hosts()),
    }

    # run_pipeline writes its report to data/staging/run_report.json under
    # the working directory.  Run in the repo (the pipeline reads its config
    # and index relative to it) and keep any existing report intact.
    report_path = REPO_ROOT / "data" / "staging" / "run_report.json"
    previous = report_path.read_bytes() if report_path.exists() else None
    report_path.unlink(missing_ok=True)

    try:
        if verbose:
            print(f"[airgap] running: {' '.join(args)}")

        result = subprocess.run(
            _child_command(args),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
        verdict["returncode"] = result.returncode

        if verbose or result.returncode != 0:
            if result.stdout:
                print("STDOUT:", result.stdout[-2000:])
            if result.stderr:
                print("STDERR:", result.stderr[-2000:])
        if "EGRESS BLOCKED" in (result.stderr or "") + (result.stdout or ""):
            verdict["egress_blocked"] = True

        if report_path.exists():
            report = json.loads(report_path.read_text())
            verdict["docs_total"] = report.get("docs_total", 0)
            verdict["docs_ok"] = report.get("docs_ok", 0)
            verdict["docs_failed"] = report.get("docs_failed", 0)
            verdict["total_persons"] = report.get("total_persons", 0)
            verdict["failures"] = report.get("failures", [])

            # Silent degradation check: documents succeeded and found persons.
            verdict["passed"] = (
                result.returncode == 0
                and verdict["docs_ok"] > 0
                and verdict["total_persons"] > 0
                and not verdict.get("egress_blocked")
            )
        else:
            verdict["no_report"] = True

        for doc_file in data_dir.glob("*.json"):
            doc = json.loads(doc_file.read_text())
            if not doc.get("persons", []):
                verdict.setdefault("empty_documents", []).append(doc_file.name)
        if verdict.get("empty_documents"):
            verdict["passed"] = False

    except Exception as e:
        verdict["exception"] = str(e)
        verdict["passed"] = False
    finally:
        if previous is not None:
            report_path.write_bytes(previous)
        else:
            report_path.unlink(missing_ok=True)

    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--subset", action="store_true",
                    help="run only the smallest fixture (Hamblin PDF)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)

    verdict = run_airgap_test(subset=args.subset, verbose=args.verbose)

    print(json.dumps({"airgap": "pass" if verdict["passed"] else "fail", **verdict}, indent=2))

    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
