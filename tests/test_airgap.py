"""M17.3 Air-gap test — assert the pipeline succeeds with egress blocked.

Run:  pytest tests/test_airgap.py
      python scripts/airgap_test.py              # full run (needs GPUStack)
      python scripts/airgap_test.py --subset     # CI-fast subset (no GPUStack needed)
"""

import json
import socket
from pathlib import Path

import pytest

from scripts import airgap_test

PERMITTED = airgap_test.PERMITTED_HOSTS


class TestPermittedHostCheck:
    """Unit tests for the allow-list logic."""

    def test_permitted_hosts_contains_gpustack(self):
        assert "gpustack.unibe.ch" in PERMITTED

    def test_case_insensitive_match(self):
        assert airgap_test._allowed_host("GPUSTACK.UNIBE.CH")
        assert airgap_test._allowed_host("Gpustack.Unibe.Ch")

    def test_rejects_external_host(self):
        assert not airgap_test._allowed_host("api.openai.com")
        assert not airgap_test._allowed_host("httpbin.org")
        assert not airgap_test._allowed_host("github.com")

    def test_resolve_atr_host_handles_missing_env(self, monkeypatch):
        monkeypatch.delenv("ATR_GATEWAY_URL", raising=False)
        monkeypatch.setattr(airgap_test, "_resolve_atr_host", lambda: set())
        result = airgap_test._resolve_atr_host()
        assert isinstance(result, set)


class TestSocketBlocking:
    """Smoke tests for the socket-blocking layer — no real network needed."""

    def test_blocked_connect_raises_permission_error(self):

        real_socket = socket.socket
        airgap_test._block_egress()
        try:
            s = socket.socket()
            with pytest.raises(PermissionError, match="EGRESS BLOCKED"):
                s.connect(("api.openai.com", 443))
        finally:
            airgap_test._unblock_egress()
            # verify socket is restored
            assert socket.socket is real_socket

    def test_permitted_connect_succeeds_to_localhost(self):
        """Connecting to a permitted host (loopback) should not be blocked."""
        airgap_test._block_egress()
        try:
            s = socket.socket()
            # localhost is not in PERMITTED_HOSTS, but we just check the
            # error message contains EGRESS BLOCKED for an unknown host
            with pytest.raises(PermissionError, match="EGRESS BLOCKED"):
                s.connect(("localhost", 9999))
        finally:
            airgap_test._unblock_egress()

    def test_unblock_restores_real_socket(self):
        original = socket.socket
        airgap_test._block_egress()
        airgap_test._unblock_egress()
        assert socket.socket is original


class TestAirgapTestEntry:
    """Tests that run_airgap_test returns the expected verdict structure."""

    def test_verdict_structure_on_subset_run(self, monkeypatch, tmp_path):
        """Verdict structure is correct regardless of pipeline outcome."""
        import subprocess
        import tempfile

        import scripts.airgap_test as a

        def fake_mkdtemp(prefix=""):
            return str(tmp_path)

        def fake_run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
            stage = Path(str(tmp_path)) / "staging"
            stage.mkdir(parents=True, exist_ok=True)
            (stage / "run_report.json").write_text(json.dumps({
                "docs_total": 1, "docs_ok": 1, "docs_failed": 0,
                "total_persons": 5, "failures": [],
            }))
            out_dir = Path(str(tmp_path)) / "site" / "data"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "doc.json").write_text(json.dumps({
                "doc_id": "test", "persons": [{"name": "Peter"}],
            }))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        # Patch at import location AND at use location
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(tempfile, "mkdtemp", fake_mkdtemp)
        monkeypatch.setattr(a.subprocess, "run", fake_run)
        monkeypatch.setattr(a, "_collect_subset", lambda d: d)

        verdict = airgap_test.run_airgap_test(subset=True, verbose=False)
        assert "ran_at" in verdict
        assert "passed" in verdict
        assert "docs_total" in verdict
        assert "permitted_hosts" in verdict
        assert verdict["permitted_hosts"] == sorted(PERMITTED)
        assert verdict["docs_ok"] == 1
        assert verdict["total_persons"] == 5

    def test_main_returns_0_on_pass(self, capsys, monkeypatch):
        """If the test passes, main() exits with status 0."""
        monkeypatch.setattr(airgap_test, "run_airgap_test", lambda **kw: {
            "ran_at": "2026-01-01T00:00:00Z",
            "subset": False,
            "passed": True,
            "docs_ok": 1,
            "docs_total": 1,
            "docs_failed": 0,
            "total_persons": 5,
            "failures": [],
            "permitted_hosts": sorted(PERMITTED),
            "returncode": 0,
        })
        exit_code = airgap_test.main(["--subset"])
        assert exit_code == 0

    def test_main_returns_1_on_fail(self, capsys, monkeypatch):
        """If the test fails, main() exits with status 1."""
        monkeypatch.setattr(airgap_test, "run_airgap_test", lambda **kw: {
            "ran_at": "2026-01-01T00:00:00Z",
            "subset": False,
            "passed": False,
            "docs_ok": 0,
            "docs_total": 1,
            "docs_failed": 1,
            "total_persons": 0,
            "failures": [{"doc": "test.pdf", "error": "no GPUStack"}],
            "permitted_hosts": sorted(PERMITTED),
            "returncode": 1,
        })
        exit_code = airgap_test.main(["--subset"])
        assert exit_code == 1
        out = capsys.readouterr().out
        assert '"airgap": "fail"' in out
