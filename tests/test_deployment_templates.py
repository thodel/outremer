from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
RENDERER_PATH = ROOT / "deploy" / "tei" / "render_config.py"
SPEC = importlib.util.spec_from_file_location("tei_render_config", RENDERER_PATH)
assert SPEC and SPEC.loader
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


def values(**overrides: str) -> dict[str, str]:
    result = {
        "PUBLIC_BASE_PATH": "/outremer/",
        "PUBLIC_BASE_PATH_NO_SLASH": "/outremer",
        "RELEASE_ROOT": "/opt/outremer",
        "STATE_ROOT": "/var/lib/outremer",
        "RUNTIME_USER": "outremer",
        "WEB_UPSTREAM": "http://127.0.0.1:8088",
        "API_UPSTREAM": "http://127.0.0.1:8089",
        "WORK_ROOT": "/home/dh/outremer/work",
        "WORKER_USER": "dh",
        "WORKER_HOME": "/home/dh",
        "NIGHTLY_LOG": "/home/dh/outremer/logs/nightly.log",
    }
    result.update(overrides)
    return result


def test_render_all_templates_without_unresolved_tokens(tmp_path: Path) -> None:
    rendered = renderer.render_directory(
        ROOT / "deploy" / "tei" / "templates", tmp_path, values()
    )

    assert {path.name for path in rendered} == {
        "outremer-web.service",
        "outremer-worker.service",
        "outremer-worker.timer",
        "outremer.nginx.conf",
    }
    combined = "\n".join(path.read_text() for path in rendered)
    assert not renderer.TOKEN_RE.search(combined)
    assert "/outremer/" in combined
    assert "/opt/outremer/current" in combined
    assert "/var/lib/outremer" in combined
    assert "ProtectSystem=strict" in combined
    assert "NoNewPrivileges=true" in combined
    assert "MemoryMax=" in combined


def test_nginx_orders_api_before_static_and_forwards_prefix(tmp_path: Path) -> None:
    renderer.render_directory(ROOT / "deploy" / "tei" / "templates", tmp_path, values())
    nginx = (tmp_path / "outremer.nginx.conf").read_text()

    assert nginx.index("location ^~ /outremer/api/") < nginx.index(
        "location ^~ /outremer/ {"
    )
    assert "proxy_set_header X-Forwarded-Prefix /outremer/;" in nginx
    assert "proxy_pass http://127.0.0.1:8088/;" in nginx
    assert "proxy_pass http://127.0.0.1:8089/;" in nginx
    assert "location = /outremer {" in nginx
    assert "return 308 /outremer/;" in nginx


@pytest.mark.parametrize("bad", ["/", "outremer/", "/outremer", "/a/b/", "/../"])
def test_public_base_path_rejects_unsafe_values(bad: str) -> None:
    with pytest.raises(Exception):
        renderer.public_base_path(bad)


@pytest.mark.parametrize("bad", ["/", "relative", "/opt/../root"])
def test_absolute_path_rejects_broad_or_unsafe_values(bad: str) -> None:
    with pytest.raises(Exception):
        renderer.absolute_path(bad)


def test_upstream_must_be_loopback() -> None:
    with pytest.raises(Exception):
        renderer.upstream("https://example.org:8088")
    with pytest.raises(Exception):
        renderer.upstream("http://0.0.0.0:8088")
    assert renderer.upstream("http://127.0.0.1:8088") == "http://127.0.0.1:8088"


def test_unknown_template_token_fails() -> None:
    with pytest.raises(ValueError, match="unknown"):
        renderer.render_text("@NOT_ALLOWED@", values())


def test_the_worker_is_the_nightly_with_its_gate(tmp_path: Path) -> None:
    """#134: the packaged worker ran run_pipeline.py alone — no gate, no publish.
    It must run nightly.sh, as the checkout's owner, logging where the
    healthcheck reads, with only the home and the mirror writable."""
    renderer.render_directory(ROOT / "deploy" / "tei" / "templates", tmp_path, values())
    unit = (tmp_path / "outremer-worker.service").read_text()
    assert "ExecStart=/bin/bash /home/dh/outremer/work/deploy/tei/nightly.sh" in unit
    assert "run_pipeline.py" not in unit.split("[Service]", 1)[1]
    assert "User=dh" in unit and "SupplementaryGroups=outremer" in unit
    assert "StandardOutput=append:/home/dh/outremer/logs/nightly.log" in unit
    assert "ReadWritePaths=/home/dh /var/lib/outremer/state/site" in unit
    assert "ProtectSystem=strict" in unit and "NoNewPrivileges=true" in unit
    timer = (tmp_path / "outremer-worker.timer").read_text()
    assert "OnCalendar=*-*-* 03:15:00 Europe/Zurich" in timer and "Persistent=true" in timer


def test_the_committed_render_matches_the_templates(tmp_path: Path) -> None:
    """rendered-tei/ is what root-install.sh installs; it must not drift."""
    import subprocess
    import sys

    subprocess.run([sys.executable, str(RENDERER_PATH), "--output-dir", str(tmp_path)], check=True,
                   capture_output=True)
    for path in tmp_path.iterdir():
        assert path.read_text() == (ROOT / "deploy" / "tei" / "rendered-tei" / path.name).read_text(), path.name


def test_nightly_gates_before_it_publishes() -> None:
    """The property the whole worker exists for: under set -e, the gate runs
    before the mirror and before any commit or push."""
    script = (ROOT / "deploy" / "tei" / "nightly.sh").read_text()
    assert "set -euo pipefail" in script
    gate = script.index("scripts/release_control.py gate")
    assert gate < script.index("rsync -rlptDO") < script.index("git push origin main")
    assert script.index("scripts/run_pipeline.py") < gate
    assert script.index("--airgap") < gate


def test_nightly_imports_adjudications_before_the_pipeline_and_publishes_them() -> None:
    """M13.3 (#179): review-API events become decisions.json and rebuilt
    fixtures before the run, and ride in the same publish commit. An
    unreachable API is a warning, never a stop."""
    script = (ROOT / "deploy" / "tei" / "nightly.sh").read_text()
    imp = script.index("scripts/import_review_decisions.py")
    assert imp < script.index("release_control.py preflight")
    assert script.index("evaluation.build_fixture --relink") < script.index("scripts/run_pipeline.py")
    assert "::warning::review import failed" in script
    publish = script[script.index("git add"):script.index("git push origin main")]
    assert "data/decisions.json" in publish and "evaluation/fixtures" in publish


def test_work_root_must_lie_inside_the_worker_home(tmp_path: Path) -> None:
    import subprocess
    import sys

    out = subprocess.run([sys.executable, str(RENDERER_PATH), "--output-dir", str(tmp_path),
                          "--work-root", "/srv/outremer/work"], capture_output=True, text=True)
    assert out.returncode != 0 and "inside --worker-home" in (out.stderr + out.stdout)
