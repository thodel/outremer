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
    assert "--evidence-dir ${OUTREMER_EVIDENCE_DIR}" in combined
    assert "--review-decisions-path ${OUTREMER_REVIEW_DECISIONS_PATH}" in combined
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
