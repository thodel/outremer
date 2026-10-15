"""ADR 0002 / #87: the ATR client is the gateway's package, installed and pinned,
never a copy in this tree.

The two consumers' private copies had diverged before the move; this is the
guard that keeps a third from appearing.
"""

import re
import sys
from pathlib import Path

import atr_client

REPO = Path(__file__).resolve().parents[1]
PIN = re.compile(
    r"^atr-client @ git\+https://github\.com/thodel/serving-atr-inference@[0-9a-f]{40}"
    r"#subdirectory=clients/python$",
    re.M,
)


def test_the_client_is_imported_from_the_installed_package_not_the_tree():
    where = Path(atr_client.__file__).resolve()
    # A dev venv may live under the repo; what matters is that the module comes
    # from an installed distribution, not from scripts/ or the tree.
    assert "site-packages" in where.parts, f"atr_client is not an installed package: {where}"
    assert not (REPO / "scripts" / "atr_client.py").exists(), "a vendored copy came back"


def test_both_requirement_files_pin_a_commit_sha():
    for name in ("requirements.txt", "requirements.lock.txt"):
        text = (REPO / name).read_text()
        assert PIN.search(text), f"{name}: no git+https pin on a 40-hex SHA for atr-client"


def test_the_pipeline_builds_the_client_from_outremer_config(monkeypatch):
    import config
    from evaluation import _pipeline

    monkeypatch.setattr(config, "ATR_GATEWAY_URL", "http://gw:8200/")
    monkeypatch.setattr(config, "ATR_API_KEY", "k")
    monkeypatch.setattr(config, "ATR_HTTP_TIMEOUT", 300.0)
    client = _pipeline.atr_client()
    assert (client.base_url, client.api_key, client.timeout) == ("http://gw:8200", "k", 300.0)
    assert sys.modules["atr_client"] is atr_client
