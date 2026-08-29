# scripts/config.py
"""
GPUStack configuration for the OUTREMER pipeline.
All LLM calls route through GPUStack on gpustack.unibe.ch.

Env vars (set in .env.gpustack, git-ignored):
    GPUSTACK_BASE_URL    - defaults to https://gpustack.unibe.ch/v1
    GPUSTACK_API_KEY     - API key for GPUStack authentication
    GPUSTACK_TIMEOUT     - request timeout in seconds (default 120)
    EXTRACTION_MODEL     - model for person extraction (default qwen3-30b-a3b-instruct)
    ORCHESTRATOR_MODEL   - model for orchestration (default minimax-m2.7)
    QWEN3_VL_MODEL       - vision model for document OCR (default qwen3-vl-30b-a3b-instruct)
    ATR_GATEWAY_URL      - serving-atr-inference base URL
    ATR_API_KEY          - static X-API-Key credential (empty for local development)
    ATR_HTTP_TIMEOUT     - gateway request timeout in seconds (default 300)
    OCR_ENGINE           - qwen3-vl | mistral (default qwen3-vl)
    EXTRACTION_SEED      - fixed chat-completion seed (default 42)
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

# ATR gateway. The 300-second client budget matches the gateway engine budget;
# shorter timeouts can misreport healthy cold-model or long-page requests.
ATR_GATEWAY_URL = _get("ATR_GATEWAY_URL", "")
ATR_API_KEY = _get("ATR_API_KEY", "")
ATR_HTTP_TIMEOUT = float(_get("ATR_HTTP_TIMEOUT", "300"))

# Model names - must match exactly how models are registered in GPUStack
EXTRACTION_MODEL   = _get("EXTRACTION_MODEL",   "qwen3-30b-a3b-instruct")
ORCHESTRATOR_MODEL = _get("ORCHESTRATOR_MODEL", "minimax-m2.7")
QWEN3_VL_MODEL     = _get("QWEN3_VL_MODEL",     "qwen3-vl-30b-a3b-instruct")
EXTRACTION_SEED    = int(_get("EXTRACTION_SEED", "42"))
# Reasoning models (gpt-oss-120b) spend tokens on reasoning before emitting
# content; a tight budget truncates the JSON mid-array. agentic_historian
# carries the same lesson as GPUSTACK_TEXT_MAX_TOKENS.
EXTRACTION_MAX_TOKENS = int(_get("EXTRACTION_MAX_TOKENS", "4096"))
# Qwen3-family hybrid models default to thinking mode: they reason silently
# until the token budget is exhausted and return an EMPTY content string
# (observed as "Unrecoverable JSON (length=0)" on tei, 2026-08-29). Setting
# this sends vLLM's chat_template_kwargs {"enable_thinking": false}.
EXTRACTION_DISABLE_THINKING = _get("EXTRACTION_DISABLE_THINKING", "false").lower() == "true"

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
