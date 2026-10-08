"""M17.3 Air-gap test — assert the pipeline succeeds with egress blocked.

Run:  pytest tests/test_airgap.py
      python scripts/airgap_test.py              # full run (needs GPUStack)
      python scripts/airgap_test.py --subset     # CI-fast subset (no GPUStack needed)
"""

import json
import socket
import subprocess
import sys

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
        real_connect = socket.socket.connect
        airgap_test._block_egress()
        try:
            s = socket.socket()
            with pytest.raises(PermissionError, match="EGRESS BLOCKED"):
                s.connect(("api.openai.com", 443))
            s.close()
        finally:
            airgap_test._unblock_egress()
        assert socket.socket.connect is real_connect

    def test_loopback_is_not_permitted(self):
        airgap_test._block_egress()
        try:
            s = socket.socket()
            with pytest.raises(PermissionError, match="EGRESS BLOCKED"):
                s.connect(("localhost", 9999))
            s.close()
        finally:
            airgap_test._unblock_egress()

    def test_permitted_address_passes_the_check(self, monkeypatch):
        """A resolved address of a permitted host is not blocked."""
        monkeypatch.setattr(airgap_test, "_resolve_permitted_addresses",
                            lambda: {"gpustack.unibe.ch", "192.0.2.7"})
        airgap_test._block_egress()
        try:
            airgap_test._check(("192.0.2.7", 443))
            airgap_test._check(("gpustack.unibe.ch", 443))
            with pytest.raises(PermissionError):
                airgap_test._check(("192.0.2.8", 443))
        finally:
            airgap_test._unblock_egress()

    def test_unix_socket_address_is_not_egress(self):
        airgap_test._check("/tmp/some.sock")

    def test_unblock_restores_real_connect(self):
        original = socket.socket.connect
        airgap_test._block_egress()
        airgap_test._unblock_egress()
        assert socket.socket.connect is original

    def test_block_holds_in_the_child_process(self):
        """The pipeline runs as a child: the block must reach it."""
        cmd = airgap_test._child_command([])
        boot = cmd[2].split("; sys.argv")[0]
        code = (
            f"{boot}; import socket\n"
            "try:\n"
            "    socket.socket().connect(('example.org', 80))\n"
            "except PermissionError as e:\n"
            "    print('BLOCKED' if 'EGRESS BLOCKED' in str(e) else 'OTHER')\n"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, timeout=60)
        assert "BLOCKED" in out.stdout, out.stderr


class TestAirgapTestEntry:
    """Tests that run_airgap_test returns the expected verdict structure."""

    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr(airgap_test, "REPO_ROOT", tmp_path / "repo")
        (tmp_path / "repo").mkdir()
        monkeypatch.setattr(airgap_test.tempfile, "mkdtemp",
                            lambda prefix="": str(tmp_path / "work"))
        (tmp_path / "work").mkdir()

    def _report(self, tmp_path, **data):
        staging = tmp_path / "repo" / "data" / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "run_report.json").write_text(json.dumps(data))

    def test_verdict_structure_on_subset_run(self, monkeypatch, tmp_path):
        """Verdict structure is correct regardless of pipeline outcome."""
        self._setup(monkeypatch, tmp_path)
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            self._report(tmp_path, docs_total=1, docs_ok=1, docs_failed=0,
                         total_persons=5, failures=[])
            (tmp_path / "work" / "site" / "data" / "doc.json").write_text(
                json.dumps({"doc_id": "test", "persons": [{"name": "Peter"}]}))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr(airgap_test.subprocess, "run", fake_run)

        verdict = airgap_test.run_airgap_test(subset=True, verbose=False)
        assert verdict["passed"] is True
        assert verdict["permitted_hosts"] == sorted(PERMITTED)
        assert verdict["docs_ok"] == 1
        assert verdict["total_persons"] == 5
        assert "--file" in seen["cmd"][2]  # subset narrows the corpus
        # the run's report is not left behind in the repo
        assert not (tmp_path / "repo" / "data" / "staging" / "run_report.json").exists()

    def test_empty_document_fails_the_run(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)

        def fake_run(*a, **k):
            self._report(tmp_path, docs_total=1, docs_ok=1, total_persons=3)
            (tmp_path / "work" / "site" / "data" / "d.json").write_text(
                json.dumps({"persons": []}))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr(airgap_test.subprocess, "run", fake_run)
        verdict = airgap_test.run_airgap_test(subset=True)
        assert verdict["passed"] is False
        assert verdict["empty_documents"] == ["d.json"]

    def test_blocked_egress_in_child_fails_the_run(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)

        def fake_run(*a, **k):
            self._report(tmp_path, docs_total=1, docs_ok=1, total_persons=3)
            return type("R", (), {"returncode": 0, "stdout": "",
                                  "stderr": "PermissionError: EGRESS BLOCKED: x"})()

        monkeypatch.setattr(airgap_test.subprocess, "run", fake_run)
        assert airgap_test.run_airgap_test(subset=True)["passed"] is False

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
