#!/usr/bin/env python3
"""
llm_client.py
─────────────
Thin GPUStack client — wraps openai.OpenAI with GPUStack base URL.
Includes exponential-backoff retry on transient failures.

Usage:
    from llm_client import generate
    text = generate("Extract persons from: ...", system="You are an expert...")
"""
from __future__ import annotations

import functools
import inspect
import logging
import re
import time
from typing import Any

import openai

from config import (
    EXTRACTION_SEED,
    GPUSTACK_API_KEY,
    GPUSTACK_BASE_URL,
    GPUSTACK_MODEL_TEXT,
    GPUSTACK_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Reusable client (singleton per process)
_client: openai.OpenAI | None = None

_SSE_PREFIX = re.compile(rb"^\s*data:\s*")
_HOP_HEADERS = {"content-length", "content-encoding", "transfer-encoding"}

# openai 2.x is built on ``httpx``, openai 3.x on its vendored ``httpx2``. The
# transport must subclass whichever the installed SDK hands its requests to,
# so take the module from the SDK's own client class rather than importing one.
httpx = inspect.getmodule(openai.DefaultHttpxClient.__mro__[1])


class LenientJSONTransport(httpx.BaseTransport):
    """Strip an SSE ``data: `` frame from a non-streaming JSON reply.

    Since 16./17.10.2026 GPUStack answers ``stream=false`` chat completions
    with ``content-type: application/json`` but a body of
    ``data: {...chat.completion...}`` — one frame, no ``[DONE]``, no newline.
    The openai SDK takes the content type at its word and fails on the first
    byte, so every extraction chunk fell back to heuristic NER and the
    provenance gate refused the night. The admins have not fixed it, so the
    client reads past the frame: only when the declared type is JSON and the
    body starts with ``data:``. Streaming replies and clean JSON pass through
    untouched. Each stripped reply is logged once per process so the
    regression stays visible in the nightly log.
    """

    def __init__(self, inner: httpx.BaseTransport | None = None) -> None:
        self._inner = inner or httpx.HTTPTransport()
        self.stripped = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        ctype = response.headers.get("content-type", "")
        if not ctype.lower().startswith("application/json"):
            return response
        response.read()  # decodes content-encoding; the body is now plain bytes
        body = response.content
        match = _SSE_PREFIX.match(body)
        if match is None:
            return response
        self.stripped += 1
        if self.stripped == 1:
            logger.warning(
                "GPUStack framed a non-streaming JSON reply as an SSE event "
                "(%s); stripping the prefix", request.url.path,
            )
        headers = [(k, v) for k, v in response.headers.raw if k.decode().lower() not in _HOP_HEADERS]
        return httpx.Response(
            response.status_code,
            headers=headers,
            content=body[match.end():],
            request=request,
            extensions=response.extensions,
        )

    def close(self) -> None:
        self._inner.close()


def get_client() -> openai.OpenAI:
    """Return a shared OpenAI client pointed at GPUSTACK_BASE_URL."""
    global _client
    if _client is None:
        _client = openai.OpenAI(
            base_url=GPUSTACK_BASE_URL,
            api_key=GPUSTACK_API_KEY or "dummy",
            timeout=GPUSTACK_TIMEOUT,
            http_client=openai.DefaultHttpxClient(transport=LenientJSONTransport()),
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
    images: list[str] | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> str:
    """
    Send a chat completion to GPUStack with automatic retry.

    Args:
        prompt   — user message
        system   — optional system prompt
        images   — optional data: URLs sent as multimodal image parts
        model    — override the TEXT role model (None = GPUSTACK_MODEL_TEXT);
                   recognition passes the VISION role model here
        **kwargs — passed through to the API (temperature, max_tokens, …)

    Returns:
        The raw ``content`` string from the first assistant message.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    if images:
        # Vision models need the image as a structured content part. Pasting a
        # base64 blob into the text prompt does NOT work: the model sees an
        # opaque token string, and a page-sized document blows the context
        # window outright (measured on tei: 65k tokens → HTTP 400).
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for data_url in images:
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})
    kwargs.setdefault("seed", EXTRACTION_SEED)

    client = get_client()
    resp = client.chat.completions.create(
        model=model or GPUSTACK_MODEL_TEXT,
        messages=messages,
        **kwargs,
    )
    choice = resp.choices[0]
    content = choice.message.content or ""
    if getattr(choice, "finish_reason", None) == "length":
        # The budget ran out. Callers only see the content string, so this is
        # the one place that can tell "truncated" — or, with no content at
        # all, "a reasoning model spent the budget thinking" — from a normal
        # short answer.
        usage = getattr(resp, "usage", None)
        logger.warning(
            "%s stopped at the token limit (%s completion tokens) with %d chars "
            "of content%s",
            model or GPUSTACK_MODEL_TEXT,
            getattr(usage, "completion_tokens", "?"),
            len(content),
            "" if content.strip() else
            " — the budget went to reasoning; send chat_template_kwargs "
            "enable_thinking=false or raise max_tokens",
        )
    return content
