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
1. The pipeline can complete end-to-end without reaching any host except
   the two permitted inference endpoints (GPUStack and the ATR gateway).
2. The output documents are non-empty: the run did not silently fall back
   to empty text or empty candidate lists.

Permitted hosts (documented in README):
    gpustack.unibe.ch        — LLM extraction and OCR
    host of ATR_GATEWAY_URL  — ATR recognition (kraken / TrOCR)

If the test fails, a future change introduced an undeclared outbound
dependency. Fix the code before merging.  Do not add the new host to this
list without updating README first.

Live-backend note
─────────────────
The pipeline run needs GPUStack (and the ATR gateway) to be reachable, with
or without --subset: --subset only shrinks the corpus.  CI therefore runs
only tests/test_airgap.py (offline); the live run belongs to the tei nightly.

How the block works
───────────────────
The pipeline runs in a child process.  The child is started through this
module, which resolves the permitted hosts to IPs *first* and then patches
socket.socket.connect, so the block holds inside the process that does the
network I/O (a patch in this parent process would not reach it).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hosts the pipeline is allowed to contact (must match README documentation).
# Update README and this list together; never add a host without the other.
# The ATR gateway host is derived from ATR_GATEWAY_URL at runtime so local
# development works without hard-coding a deployment hostname.
PERMITTED_HOSTS = frozenset({
    "gpustack.unibe.ch",
})

SUBSET_SOURCES = ["Hamblin-MuslimPerspectivesMilitary-2001.pdf"]

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_allowed_extra: set[str] = set()


def _allowed_host(host: str) -> bool:
    """True when host is a permitted name or a resolved permitted address."""
    h = host.casefold()
    return h in {p.casefold() for p in PERMITTED_HOSTS} or host in _allowed_extra


def _atr_host() -> str | None:
    """Host of ATR_GATEWAY_URL (env first, then scripts.config), or None."""
    url = os.environ.get("ATR_GATEWAY_URL", "")
    if not url:
        try:
            sys.path.insert(0, str(REPO_ROOT / "scripts"))
            from config import ATR_GATEWAY_URL as url  # type: ignore[no-redef]
        except Exception:
            url = ""
    return urlparse(url).hostname if url else None


def _resolve_atr_host() -> set[str]:
    """The ATR gateway host name, if configured."""
    host = _atr_host()
    return {host} if host else set()


def _resolve_permitted_addresses() -> set[str]:
    """Names and IPs of all permitted hosts, resolved before egress is cut.

    Clients resolve the name and then connect() to the IP, so the allow-list
    has to know the addresses, not only the names.
    """
    allowed: set[str] = set()
    for host in set(PERMITTED_HOSTS) | _resolve_atr_host():
        allowed.add(host)
        try:
            for info in socket.getaddrinfo(host, None):
                allowed.add(info[4][0])
        except OSError:
            pass  # unresolvable now: the name stays allowed, the run will fail loudly
    return allowed


def _check(address) -> None:
    # AF_UNIX addresses are str/bytes paths, not (host, port) tuples.
    if not isinstance(address, tuple) or not address:
        return
    host = address[0]
    if not _allowed_host(str(host)):
        raise PermissionError(
            f"EGRESS BLOCKED: connecting to {host}:{address[1:2]} "
            f"is not in the permitted set {sorted(PERMITTED_HOSTS)} + ATR gateway"
        )


def _block_egress() -> None:
    """Refuse outbound connect() to anything but the permitted hosts."""
    _allowed_extra.update(_resolve_permitted_addresses())

    def connect(self, address):
        _check(address)
        return _original_connect(self, address)

    def connect_ex(self, address):
        _check(address)
        return _original_connect_ex(self, address)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]


def _unblock_egress() -> None:
    """Restore the real connect()."""
    socket.socket.connect = _original_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _original_connect_ex  # type: ignore[method-assign]
    _allowed_extra.clear()


def _child_command(args: list[str]) -> list[str]:
    """Command that blocks egress inside the child, then runs run_pipeline."""
    boot = (
        "import runpy, sys; "
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r}); "
        "import airgap_test; airgap_test._block_egress(); "
        f"sys.argv = {['run_pipeline.py'] + args!r}; "
        f"runpy.run_path({str(REPO_ROOT / 'scripts' / 'run_pipeline.py')!r}, run_name='__main__')"
    )
    return [sys.executable, "-c", boot]


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
        "permitted_hosts": sorted(PERMITTED_HOSTS),
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
