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

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).parent.parent

# ── Explicit .env loading ────────────────────────────────────────────────────
# Load .env.gpustack (local GPUStack credentials) and .env (optional overrides).
# Environment variables (from the shell) always take precedence over both files.
_dotenv_path = _REPO_ROOT / ".env.gpustack"
if _dotenv_path.exists():
    load_dotenv(_dotenv_path, override=False)   # shell env wins if key is already set
else:
    _untracked = _REPO_ROOT / ".env.gpustack"
    logging.warning(
        "GPUStack env file not found at %s — set up .env.gpustack "
        "(see README §Configuration).",
        _untracked,
    )

_dotenv_fallback = _REPO_ROOT / ".env"
load_dotenv(_dotenv_fallback, override=False)   # shell / .env.gpustack still wins


def _get(key: str, default=None):
    return os.environ.get(key, default)


# ── GPUStack ─────────────────────────────────────────────────────────────────
GPUSTACK_BASE_URL  = _get("GPUSTACK_BASE_URL",  "https://gpustack.unibe.ch/v1")
GPUSTACK_API_KEY   = _get("GPUSTACK_API_KEY",   "")
GPUSTACK_TIMEOUT   = int(_get("GPUSTACK_TIMEOUT", "120"))

# Model names — must match exactly how models are registered in GPUStack
EXTRACTION_MODEL   = _get("EXTRACTION_MODEL",   "qwen3-30b-a3b-instruct")
ORCHESTRATOR_MODEL = _get("ORCHESTRATOR_MODEL", "minimax-m2.7")

# ── VL model (OCR) ─────────────────────────────────────────────────────────────
QWEN3_VL_MODEL   = _get("QWEN3_VL_MODEL",   "qwen3-vl-30b-instruct")

# ── OCR ──────────────────────────────────────────────────────────────────────
# "easyocr"  — local CPU/GPU, no API call (preferred for speed/cost)
# "gpustack" — GPUStack MiniMax-M2.7 for document-level OCR
# "mistral"  — Mistral API (legacy fallback)
OCR_ENGINE = _get("OCR_ENGINE", "easyocr")


def gpustack_enabled() -> bool:
    """True when GPUStack is the configured extraction path."""
    return bool(GPUSTACK_API_KEY) or OCR_ENGINE == "gpustack"


def log_active_engines() -> None:
    """Log the active extraction + OCR engines at startup."""
    if gpustack_enabled():
        extraction = f"{GPUSTACK_BASE_URL}/{EXTRACTION_MODEL}"
        logging.info(
            "Extraction: GPUStack (%s)  [timeout=%ds]",
            extraction,
            GPUSTACK_TIMEOUT,
        )
    else:
        logging.info(
            "Extraction: HEURISTIC (no GPUStack credentials — set GPUSTACK_API_KEY "
            "in .env.gpustack to enable AI-powered extraction)"
        )

    ocr_label = {
        "easyocr": "EasyOCR (local CPU/GPU, no API)",
        "gpustack": f"GPUStack MiniMax-M2.7 ({GPUSTACK_BASE_URL})",
        "mistral": "Mistral OCR (API)",
    }.get(OCR_ENGINE, OCR_ENGINE)
    logging.info("OCR engine: %s", ocr_label)
