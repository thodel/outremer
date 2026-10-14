"""M18.2 (#88): call sites name roles; the environment names models.

Resolution per role: GPUSTACK_MODEL_<ROLE>, then the legacy key, then the
default — and every run says which key supplied each role.
"""

import json

import nightly_status
import release_control
import run_pipeline

import config


def test_role_key_beats_legacy_key_beats_default():
    env = {"GPUSTACK_MODEL_TEXT": "role-model", "EXTRACTION_MODEL": "legacy-model"}
    assert config.resolve_model_role("text", env) == ("role-model", "GPUSTACK_MODEL_TEXT")
    assert config.resolve_model_role("text", {"EXTRACTION_MODEL": "legacy-model"}) == (
        "legacy-model", "EXTRACTION_MODEL")
    assert config.resolve_model_role("text", {}) == ("qwen3.8-27b", "default")
    assert config.resolve_model_role("vision", {"QWEN3_VL_MODEL": "v"}) == ("v", "QWEN3_VL_MODEL")
    assert config.resolve_model_role("orchestrator", {}) == ("minimax-m2.7", "default")


def test_an_empty_role_key_does_not_shadow_the_legacy_key():
    env = {"GPUSTACK_MODEL_VISION": "", "QWEN3_VL_MODEL": "legacy-vision"}
    assert config.resolve_model_role("vision", env) == ("legacy-vision", "QWEN3_VL_MODEL")


def test_model_roles_mapping_carries_the_source_of_every_role():
    env = {"GPUSTACK_MODEL_TEXT": "t", "QWEN3_VL_MODEL": "v"}
    assert config.model_roles(env) == {
        "text": {"model": "t", "source": "GPUSTACK_MODEL_TEXT"},
        "vision": {"model": "v", "source": "QWEN3_VL_MODEL"},
        "orchestrator": {"model": "minimax-m2.7", "source": "default"},
    }


def test_legacy_constants_are_aliases_of_the_roles():
    assert config.EXTRACTION_MODEL == config.GPUSTACK_MODEL_TEXT
    assert config.QWEN3_VL_MODEL == config.GPUSTACK_MODEL_VISION
    assert config.ORCHESTRATOR_MODEL == config.GPUSTACK_MODEL_ORCHESTRATOR


def test_run_report_and_status_carry_the_resolved_mapping(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "staging").mkdir(parents=True)
    mapping = config.model_roles({"EXTRACTION_MODEL": "qwen3.8-27b", "QWEN3_VL_MODEL": "qwen3.8-27b"})
    run_pipeline._write_run_report(
        run_at="2026-10-14T00:00:00+00:00", docs_total=1, docs_ok=1, docs_failed=0,
        total_persons=3, extraction_model="qwen3.8-27b", extraction_seed=42,
        ocr_engine="qwen3-vl", failures=[], models=mapping,
    )
    report_path = tmp_path / "data" / "staging" / "run_report.json"
    report = json.loads(report_path.read_text())
    assert report["models"]["text"] == {"model": "qwen3.8-27b", "source": "EXTRACTION_MODEL"}
    assert report["models"]["orchestrator"]["source"] == "default"
    status = nightly_status.build_status(report_path, None, None)
    assert status["run"]["models"] == report["models"]


def test_preflight_accepts_a_role_by_its_role_key_or_its_legacy_key(monkeypatch):
    cap = {"id": "gpustack", "kind": "openai_models", "url_env": "U", "auth": "none",
           "required_model_roles": ["text", "vision"]}
    served = {"data": [{"id": "qwen3.8-27b"}, {"id": "other"}]}
    monkeypatch.setattr(release_control, "request", lambda *a, **k: (200, served, {}))
    ok = release_control.check_capability(
        cap, {"U": "https://g.example/v1", "GPUSTACK_MODEL_TEXT": "qwen3.8-27b", "QWEN3_VL_MODEL": "qwen3.8-27b"})
    assert ok["status"] == "available"
    try:
        release_control.check_capability(
            cap, {"U": "https://g.example/v1", "GPUSTACK_MODEL_TEXT": "qwen3.8-27b"})
    except release_control.ReleaseControlError as exc:
        assert "vision" in str(exc) and "GPUSTACK_MODEL_VISION" in str(exc)
    else:
        raise AssertionError("an unconfigured required role must fail preflight")
    try:
        release_control.check_capability(
            cap, {"U": "https://g.example/v1", "GPUSTACK_MODEL_TEXT": "gone", "QWEN3_VL_MODEL": "qwen3.8-27b"})
    except release_control.ReleaseControlError as exc:
        assert "gone" in str(exc)
    else:
        raise AssertionError("a role naming an unserved model must fail preflight")
