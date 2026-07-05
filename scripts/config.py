# scripts/config.py
"""
GPUStack configuration for the OUTREMER pipeline.
All LLM calls route through GPUStack on tei.dh.unibe.ch.

Env vars (set in .env.gpustack, git-ignored):
    GPUSTACK_BASE_URL      — defaults to https://tei.dh.unibe.ch/v1
    GPUSTACK_API_KEY       — API key for GPUStack authentication
    GPUSTACK_TIMEOUT       — request timeout in seconds (default 120)
    EXTRACTION_MODEL       — model for person extraction (default qwen3-30b-a3b-instruct)
    ORCHESTRATOR_MODEL     — model for orchestration/OCR (default minimax-m2.7)
    OCR_ENGINE             — easyocr | gpustack | mistral (default easyocr)
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


def _get(key: str, default=None):
    return os.environ.get(key, default)


# ── GPUStack ────────────────────────────────────────────────────────────────
GPUSTACK_BASE_URL  = _get("GPUSTACK_BASE_URL",  "https://gpustack.unibe.ch/v1")
GPUSTACK_API_KEY   = os.environ.get("GPUSTACK_API_KEY", "")
GPUSTACK_TIMEOUT   = int(_get("GPUSTACK_TIMEOUT", "120"))

# Model names — must match exactly how models are registered in GPUStack
EXTRACTION_MODEL   = _get("EXTRACTION_MODEL",   "qwen3-30b-a3b-instruct")
ORCHESTRATOR_MODEL = _get("ORCHESTRATOR_MODEL", "minimax-m2.7")

# ── OCR ─────────────────────────────────────────────────────────────────────
# "easyocr"  — local CPU/GPU, no API call (preferred for speed/cost)
# "gpustack" — GPUStack MiniMax-M2.7 for document-level OCR
# "mistral"  — Mistral API (legacy fallback)
OCR_ENGINE = _get("OCR_ENGINE", "easyocr")
