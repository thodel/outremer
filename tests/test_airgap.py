"""M17.3 — the egress guard (scripts/airgap.py) and the air-gap test runner.

Run:  pytest tests/test_airgap.py
      python scripts/airgap_test.py --subset     # end-to-end, needs GPUStack
"""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import airgap, airgap_test

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def guard_off():
    """Leave no guard behind whatever a test does."""
    yield
    airgap.unblock_egress()


class TestPermittedHosts:
    def test_hosts_come_from_the_configured_urls(self, monkeypatch):
        monkeypatch.setenv("GPUSTACK_BASE_URL", "https://GPUStack.unibe.ch/v1")
        monkeypatch.setenv("ATR_GATEWAY_URL", "http://130.92.59.240:8200")
        monkeypatch.setenv("MCP_BASE_URL", "https://tei.dh.unibe.ch/mcp")
        assert airgap.permitted_hosts() == {
            "gpustack.unibe.ch", "130.92.59.240", "tei.dh.unibe.ch",
        }

    def test_unset_services_add_no_host(self, monkeypatch):
        monkeypatch.setenv("GPUSTACK_BASE_URL", "https://gpustack.unibe.ch/v1")
        monkeypatch.setenv("ATR_GATEWAY_URL", "")
        monkeypatch.setenv("MCP_BASE_URL", "")
        assert airgap.permitted_hosts() == {"gpustack.unibe.ch"}

    def test_wikidata_is_never_permitted(self, monkeypatch):
        monkeypatch.setenv("GPUSTACK_BASE_URL", "https://gpustack.unibe.ch/v1")
        assert "query.wikidata.org" not in airgap.permitted_hosts()


class TestGuard:
    def test_blocked_connect_raises_permission_error(self, guard_off):
        airgap.block_egress({"gpustack.unibe.ch"})
        s = socket.socket()
        with pytest.raises(PermissionError, match="EGRESS BLOCKED"):
            s.connect(("api.openai.com", 443))
        with pytest.raises(PermissionError, match="EGRESS BLOCKED"):
            s.connect_ex(("query.wikidata.org", 443))
        s.close()

    def test_loopback_is_not_permitted(self, guard_off):
        airgap.block_egress({"gpustack.unibe.ch"})
        with pytest.raises(PermissionError, match="EGRESS BLOCKED"):
            socket.socket().connect(("localhost", 9999))

    def test_permitted_name_and_resolved_address_pass(self, guard_off, monkeypatch):
        monkeypatch.setattr(airgap, "resolve_permitted_addresses",
                            lambda hosts=None: {"gpustack.unibe.ch", "192.0.2.7"})
        airgap.block_egress()
        airgap.check(("192.0.2.7", 443))
        airgap.check(("GPUSTACK.UNIBE.CH", 443))
        with pytest.raises(PermissionError):
            airgap.check(("192.0.2.8", 443))

    def test_unix_socket_address_is_not_egress(self, guard_off):
        airgap.block_egress({"gpustack.unibe.ch"})
        airgap.check("/tmp/some.sock")

    def test_blocking_exports_the_flag_and_unblock_restores(self, guard_off):
        original = socket.socket.connect
        airgap.block_egress({"gpustack.unibe.ch"})
        assert os.environ.get(airgap.ENV_FLAG) == "1"
        assert airgap.is_active()
        airgap.unblock_egress()
        assert socket.socket.connect is original
        assert airgap.ENV_FLAG not in os.environ

    def test_install_if_requested_honours_the_flag(self, guard_off, monkeypatch):
        monkeypatch.delenv(airgap.ENV_FLAG, raising=False)
        assert airgap.install_if_requested() is False
        assert not airgap.is_active()
        monkeypatch.setenv(airgap.ENV_FLAG, "1")
        assert airgap.install_if_requested() is True
        assert airgap.is_active()


class TestGuardReachesEveryProcess:
    """The pipeline and the reconciliation it spawns both do network I/O."""

    def _run(self, code: str, env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            timeout=60, cwd=REPO_ROOT,
            env={**os.environ, "GPUSTACK_BASE_URL": "https://gpustack.unibe.ch/v1",
                 "ATR_GATEWAY_URL": "", "MCP_BASE_URL": "", **env},
        )

    PROBE = (
        "import sys, socket; sys.path.insert(0, 'scripts'); import airgap\n"
        "airgap.install_if_requested()\n"
        "try:\n"
        "    socket.socket().connect(('example.org', 80))\n"
        "    print('OPEN')\n"
        "except PermissionError as e:\n"
        "    print('BLOCKED' if 'EGRESS BLOCKED' in str(e) else 'OTHER')\n"
        "except OSError:\n"
        "    print('OPEN')\n"
    )

    def test_child_inherits_the_guard_through_the_environment(self):
        out = self._run(self.PROBE, {airgap.ENV_FLAG: "1"})
        assert out.stdout.strip() == "BLOCKED", out.stderr

    def test_without_the_flag_nothing_is_blocked(self):
        out = self._run(self.PROBE, {airgap.ENV_FLAG: ""})
        assert out.stdout.strip() == "OPEN", out.stderr

    def test_pipeline_flag_blocks_the_reconciliation_subprocess(self, tmp_path):
        """run_pipeline --airgap → OUTREMER_AIRGAP=1 → wikidata_reconcile refuses egress."""
        code = (
            "import sys, runpy, subprocess\n"
            "sys.path.insert(0, 'scripts'); import airgap\n"
            "airgap.block_egress({'gpustack.unibe.ch'})\n"  # what --airgap does
            "import os\n"
            "r = subprocess.run([sys.executable, '-c', '''\n"
            "import sys, urllib.request; sys.path.insert(0, \"scripts\"); import airgap\n"
            "airgap.install_if_requested()\n"
            "try:\n"
            "    urllib.request.urlopen(\"https://query.wikidata.org/sparql\", timeout=5)\n"
            "    print(\"OPEN\")\n"
            "except Exception as e:\n"
            "    print(\"BLOCKED\" if \"EGRESS BLOCKED\" in str(e) else \"OTHER:\" + repr(e))\n"
            "'''], capture_output=True, text=True)\n"
            "print(r.stdout.strip())\n"
        )
        out = self._run(code, {})
        assert out.stdout.strip() == "BLOCKED", out.stdout + out.stderr

    def test_run_pipeline_exposes_the_flag(self):
        out = subprocess.run(
            [sys.executable, "scripts/run_pipeline.py", "--help"],
            capture_output=True, text=True, timeout=60, cwd=REPO_ROOT,
        )
        assert "--airgap" in out.stdout


class TestAirgapTestRunner:
    """run_airgap_test returns the expected verdict structure."""

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

    def test_child_is_the_pipeline_with_the_flag(self):
        cmd = airgap_test._child_command(["--file", "x.pdf"])
        assert cmd[0] == sys.executable
        assert cmd[1].endswith("run_pipeline.py")
        assert "--airgap" in cmd
        assert cmd[-2:] == ["--file", "x.pdf"]

    def test_verdict_structure_on_subset_run(self, monkeypatch, tmp_path):
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
        assert verdict["permitted_hosts"] == sorted(airgap.permitted_hosts())
        assert verdict["docs_ok"] == 1
        assert verdict["total_persons"] == 5
        assert "--airgap" in seen["cmd"]
        assert "--file" in seen["cmd"]  # subset narrows the corpus
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

    @pytest.mark.parametrize("passed,code", [(True, 0), (False, 1)])
    def test_main_exit_status(self, capsys, monkeypatch, passed, code):
        monkeypatch.setattr(airgap_test, "run_airgap_test", lambda **kw: {
            "ran_at": "2026-01-01T00:00:00Z", "subset": True, "passed": passed,
            "docs_ok": int(passed), "docs_total": 1, "docs_failed": int(not passed),
            "total_persons": 5 if passed else 0, "failures": [],
            "permitted_hosts": ["gpustack.unibe.ch"], "returncode": code,
        })
        assert airgap_test.main(["--subset"]) == code
        assert f'"airgap": "{"pass" if passed else "fail"}"' in capsys.readouterr().out
