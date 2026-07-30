# scripts/config.py
"""
GPUStack configuration for the OUTREMER pipeline.
All LLM calls route through GPUStack on gpustack.unibe.ch.

Env vars (set in .env.gpustack, git-ignored):
    GPUSTACK_BASE_URL    - defaults to https://gpustack.unibe.ch/v1
    GPUSTACK_API_KEY     - API key for GPUStack authentication
    GPUSTACK_TIMEOUT     - request timeout in seconds (default 120)
    GPUSTACK_MODEL_TEXT          - text extraction/metadata model (default gpt-oss-120b)
    GPUSTACK_MODEL_ORCHESTRATOR  - orchestration model (default minimax-m2.7)
    GPUSTACK_MODEL_VISION        - document OCR model (default qwen3-vl-30b-a3b-instruct)
    EXTRACTION_MODEL, ORCHESTRATOR_MODEL, and QWEN3_VL_MODEL remain supported
        as deprecated aliases.
    OCR_ENGINE           - qwen3-vl | mistral (default qwen3-vl)
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines from an .env-style file into os.environ.

    Existing environment variables take precedence (setdefault), so an
    explicit export or CI secret always wins over the file. Missing file,
    blank lines, and ``#`` comments are ignored.
    """
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


# Load .env.gpustack so env vars are available before config reads them.
_load_env_file(_REPO_ROOT / ".env.gpustack")


def _get(key: str, default=None):
    return os.environ.get(key, default)


# GPUStack
GPUSTACK_BASE_URL  = _get("GPUSTACK_BASE_URL",  "https://gpustack.unibe.ch/v1")
GPUSTACK_API_KEY   = os.environ.get("GPUSTACK_API_KEY", "")
GPUSTACK_TIMEOUT   = int(_get("GPUSTACK_TIMEOUT", "120"))

def resolve_model_roles(environ: os._Environ[str] | dict[str, str]) -> dict[str, str]:
    """Resolve role-based models, with deprecated environment aliases."""
    return {
        "VISION": environ.get(
            "GPUSTACK_MODEL_VISION",
            environ.get("QWEN3_VL_MODEL", "qwen3-vl-30b-a3b-instruct"),
        ),
        "TEXT": environ.get(
            "GPUSTACK_MODEL_TEXT",
            environ.get("EXTRACTION_MODEL", "gpt-oss-120b"),
        ),
        "ORCH": environ.get(
            "GPUSTACK_MODEL_ORCHESTRATOR",
            environ.get("ORCHESTRATOR_MODEL", "minimax-m2.7"),
        ),
    }


# Model names must match exactly how models are registered in GPUStack.
MODEL_ROLES = resolve_model_roles(os.environ)
GPUSTACK_MODEL_VISION = MODEL_ROLES["VISION"]
GPUSTACK_MODEL_TEXT = MODEL_ROLES["TEXT"]
GPUSTACK_MODEL_ORCHESTRATOR = MODEL_ROLES["ORCH"]

# Deprecated Python aliases retained for downstream compatibility.
QWEN3_VL_MODEL = GPUSTACK_MODEL_VISION
EXTRACTION_MODEL = GPUSTACK_MODEL_TEXT
ORCHESTRATOR_MODEL = GPUSTACK_MODEL_ORCHESTRATOR

# OCR
# "qwen3-vl" - GPUStack Qwen3 VL (default); falls back to Mistral if empty
# "mistral"  - Mistral API only (legacy; needs `pip install mistralai`
#              and MISTRAL_API_KEY)
OCR_ENGINE = _get("OCR_ENGINE", "qwen3-vl")

# Linker thresholds (M10.3) - operating point documented in
# evaluation/THRESHOLDS.md; sweep with `python -m evaluation.sweep`
LINK_CANDIDATE_FLOOR = float(_get("LINK_CANDIDATE_FLOOR", "0.60"))
LINK_MEDIUM          = float(_get("LINK_MEDIUM", "0.75"))
LINK_HIGH            = float(_get("LINK_HIGH", "0.90"))
