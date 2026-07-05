#!/usr/bin/env python3
"""
llm_client.py
─────────────
Thin GPUStack client — wraps openai.OpenAI with GPUStack base URL.
Includes exponential-backoff retry on transient failures.

Usage:
    from scripts.llm_client import generate
    text = generate("Extract persons from: ...", system="You are an expert...")
"""
from __future__ import annotations

import logging
import time
import functools
from typing import Any

import openai

from config import (
    GPUSTACK_API_KEY,
    GPUSTACK_BASE_URL,
    GPUSTACK_TIMEOUT,
    EXTRACTION_MODEL,
)

logger = logging.getLogger(__name__)

# Reusable client (singleton per process)
_client: openai.OpenAI | None = None


def get_client() -> openai.OpenAI:
    """Return a shared OpenAI client pointed at GPUSTACK_BASE_URL."""
    global _client
    if _client is None:
        _client = openai.OpenAI(
            base_url=GPUSTACK_BASE_URL,
            api_key=GPUSTACK_API_KEY or "dummy",
            timeout=GPUSTACK_TIMEOUT,
        )
    return _client


def with_retry(max_attempts: int = 3, base_delay: float = 2.0):
    """
    Decorator: retry a function with exponential backoff on exception.

    Retries on all exceptions; logs each attempt.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Retry %d/%d for %s after %.1fs: %s",
                        attempt + 1, max_attempts, fn.__name__, delay, exc
                    )
                    time.sleep(delay)
            raise RuntimeError("Unreachable")
        return wrapper
    return decorator


@with_retry(max_attempts=3, base_delay=2.0)
def generate(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> str:
    """
    Send a chat completion to GPUStack with automatic retry.

    Args:
        prompt   — user message
        system   — optional system prompt
        model    — override EXTRACTION_MODEL (None = use config default)
        **kwargs — passed through to the API (temperature, max_tokens, …)

    Returns:
        The raw ``content`` string from the first assistant message.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    client = get_client()
    resp = client.chat.completions.create(
        model=model or EXTRACTION_MODEL,
        messages=messages,
        **kwargs,
    )
    return resp.choices[0].message.content or ""
