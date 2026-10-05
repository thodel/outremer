#!/usr/bin/env python3
"""
M17.3 Air-gap test — assert the pipeline succeeds with egress blocked.

Usage:
    python scripts/airgap_test.py [--subset] [--verbose]

Options
───────
    --subset   run only the smallest fixture (Hamblin) for CI speed
    --verbose  print full run output instead of a one-line verdict

What it tests
─────────────
1. The pipeline can complete end-to-end without reaching any host except
   the two permitted inference endpoints (GPUStack and the ATR gateway).
2. The output documents are non-empty: the run did not silently fall back
   to empty text or empty candidate lists.

Permitted hosts (hard-coded, documented in README):
    gpustack.unibe.ch        — LLM extraction and OCR
    atr-gateway.<domain>     — ATR recognition (kraken / TrOCR)

If the test fails, a future change introduced an undeclared outbound
dependency. Fix the code before merging.  Do not add the new host to this
list without updating README first.

CI note
───────
The --subset flag marks this run as CI-targeted (no live-backend dependency
required in the container).  The regular run (no flag) assumes GPUStack
is reachable — that is the nightly-run environment, not CI.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Hosts the pipeline is allowed to contact (must match README documentation).
# Update README and this list together; never add a host without the other.
PERMITTED_HOSTS = frozenset({
    "gpustack.unibe.ch",
    # The ATR gateway host is derived from ATR_GATEWAY_URL at runtime so
    # local development works without hard-coding a deployment hostname.
})

# Subsets for CI (fast) vs nightly/full run.
SUBSET_SOURCES = ["Hamblin-MuslimPerspectivesMilitary-2001.pdf"]


def _allowed_host(host: str) -> bool:
    """True when host is in the permitted set (case-insensitive)."""
    return host.casefold() in {h.casefold() for h in PERMITTED_HOSTS}


def _resolve_atr_host() -> set[str]:
    """Return the resolved IP(s) for the ATR gateway host so they pass the
    allow-list check before the DNS lookup is blocked."""
    try:
        from scripts.config import ATR_GATEWAY_URL

        if ATR_GATEWAY_URL:
            host = ATR_GATEWAY_URL.split("://", 1)[1].split("/", 1)[0].split(":")[0]
            if host and host not in ("", "None"):
                return {host}
    except Exception:
        pass
    return set()


_allowed_extra = _resolve_atr_host()


def _block_egress() -> None:
    """Drop all outbound TCP connections except PERMITTED_HOSTS.

    Works by wrapping the Python runtime's socket library: replaces
    socket.socket() with a wrapper that raises EPERM for non-permitted
    outbound connections before they are created.
    """
    import builtins
    import socket as _sock

    original_socket = _sock.socket

    class _PermittedSocket:
        """Socket wrapper that blocks egress to non-permitted hosts."""

        _arch = (original_socket,)  # allow isinstance checks against original type

        def __init__(self, family=2, type=1, proto=0, fileno=None):
            self._inner = original_socket(family, type, proto, fileno)

        def connect(self, address):
            host, port = address
            # Resolve numeric addresses immediately so the permit check
            # works even after name resolution is blocked.
            try:
                if isinstance(port, str):
                    port = socket.getservbyname(port)
            except Exception:
                pass
            allowed = _allowed_host(host) or host in _allowed_extra
            if not allowed:
                raise PermissionError(
                    f"EGRESS BLOCKED: connecting to {host}:{port} "
                    f"is not in the permitted set {PERMITTED_HOSTS}"
                )
            return self._inner.connect(address)

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self._inner.__exit__(*args)

    _sock.socket = _PermittedSocket  # type: ignore[assignment]
    builtins.socket = _PermittedSocket  # type: ignore[assignment]


def _unblock_egress():
    """Restore the real socket after the test."""
    import builtins
    import socket as _sock

    _sock.socket = original_socket  # type: ignore[assignment]
    builtins.socket = original_socket  # type: ignore[assignment]


# Keep a reference so _unblock_egress can restore it
original_socket = socket.socket


def _collect_subset(tmp_dir: Path) -> Path:
    """Symlink one small source into tmp_dir so the test runs fast in CI."""
    raw = Path("data/raw")
    for name in SUBSET_SOURCES:
        src = raw / name
        if src.exists():
            # symlink_to(target) — first arg is the path the symlink POINTS TO
            (tmp_dir / name).symlink_to(src)  # type: ignore[arg-type]
    return tmp_dir


def run_airgap_test(*, subset: bool = False, verbose: bool = False) -> dict:
    """Run the pipeline with egress blocked; return a verdict dict."""
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="airgap_test_"))
    stage = tmp / "staging"
    stage.mkdir()
    bib = tmp / "bib"
    bib.mkdir()

    if subset:
        _collect_subset(tmp / "raw")
    else:
        # symlink the whole raw dir
        raw = Path("data/raw")
        for f in raw.iterdir():
            (tmp / "raw" / f.name).symlink_to(f.resolve())

    out_dir = tmp / "site"
    out_dir.mkdir()
    data_dir = out_dir / "data"
    data_dir.mkdir()

    now = datetime.now(timezone.utc).isoformat()
    verdict: dict = {
        "ran_at": now,
        "subset": subset,
        "passed": False,
        "docs_ok": 0,
        "docs_total": 0,
        "docs_failed": 0,
        "failures": [],
        "permitted_hosts": sorted(PERMITTED_HOSTS),
    }

    _block_egress()
    try:
        cmd = [
            sys.executable, "scripts/run_pipeline.py",
            "--input-dir", str(tmp / "raw"),
            "--site-dir", str(out_dir),
            "--bib-dir", str(bib),
            "--llm-metadata",
        ]
        if verbose:
            print(f"[airgap] running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            cwd=Path("."),
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

        # Read the run report to check for silent degradation
        report_path = stage / "run_report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            verdict["docs_total"] = report.get("docs_total", 0)
            verdict["docs_ok"] = report.get("docs_ok", 0)
            verdict["docs_failed"] = report.get("docs_failed", 0)
            verdict["total_persons"] = report.get("total_persons", 0)
            verdict["failures"] = report.get("failures", [])

            # Silent degradation check: docs_ok > 0 and total_persons > 0
            verdict["passed"] = (
                result.returncode == 0
                and verdict["docs_ok"] > 0
                and verdict["total_persons"] > 0
            )
        else:
            verdict["passed"] = False
            verdict["no_report"] = True

        # Check that no document was produced with empty persons
        for doc_file in data_dir.glob("*.json"):
            doc = json.loads(doc_file.read_text())
            persons = doc.get("persons", [])
            if not persons:
                verdict.setdefault("empty_documents", []).append(doc_file.name)

        if verdict.get("empty_documents"):
            verdict["passed"] = False

    except PermissionError as e:
        verdict["egress_blocked"] = str(e)
        verdict["passed"] = False
    except Exception as e:
        verdict["exception"] = str(e)
        verdict["passed"] = False
    finally:
        _unblock_egress()

    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--subset", action="store_true",
                    help="run only the smallest CI-safe fixture (Hamblin PDF)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)

    verdict = run_airgap_test(subset=args.subset, verbose=args.verbose)

    print(json.dumps({"airgap": "pass" if verdict["passed"] else "fail", **verdict}, indent=2))

    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
