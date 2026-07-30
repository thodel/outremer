"""Tests for role-based GPUStack model configuration."""

from config import resolve_model_roles


def test_role_model_defaults():
    assert resolve_model_roles({}) == {
        "VISION": "qwen3-vl-30b-a3b-instruct",
        "TEXT": "gpt-oss-120b",
        "ORCH": "minimax-m2.7",
    }


def test_deprecated_model_aliases_are_supported():
    roles = resolve_model_roles(
        {
            "QWEN3_VL_MODEL": "legacy-vision",
            "EXTRACTION_MODEL": "legacy-text",
            "ORCHESTRATOR_MODEL": "legacy-orchestrator",
        }
    )
    assert roles == {
        "VISION": "legacy-vision",
        "TEXT": "legacy-text",
        "ORCH": "legacy-orchestrator",
    }


def test_role_keys_take_precedence_over_deprecated_aliases():
    roles = resolve_model_roles(
        {
            "GPUSTACK_MODEL_VISION": "role-vision",
            "GPUSTACK_MODEL_TEXT": "role-text",
            "GPUSTACK_MODEL_ORCHESTRATOR": "role-orchestrator",
            "QWEN3_VL_MODEL": "legacy-vision",
            "EXTRACTION_MODEL": "legacy-text",
            "ORCHESTRATOR_MODEL": "legacy-orchestrator",
        }
    )
    assert roles == {
        "VISION": "role-vision",
        "TEXT": "role-text",
        "ORCH": "role-orchestrator",
    }
