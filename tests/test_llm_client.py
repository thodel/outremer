"""Unit tests for scripts/llm_client.py — mocked client, no network.

The manual smoke test against the real GPUStack endpoint lives in
scripts/test_llm_client.py; these tests cover the retry/backoff and
message-building logic offline.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import llm_client
import pytest
from llm_client import generate, with_retry


def _response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


@pytest.fixture
def fake_client(monkeypatch):
    client = MagicMock()
    client.chat.completions.create.return_value = _response("hello")
    monkeypatch.setattr(llm_client, "_client", client)
    # retries must not actually sleep in tests
    monkeypatch.setattr(llm_client.time, "sleep", lambda _s: None)
    return client


def test_generate_builds_messages_with_system(fake_client):
    out = generate("the prompt", system="the system")
    assert out == "hello"
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["messages"] == [
        {"role": "system", "content": "the system"},
        {"role": "user", "content": "the prompt"},
    ]


def test_generate_defaults_to_extraction_model(fake_client):
    generate("p")
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == llm_client.GPUSTACK_MODEL_TEXT
    assert kwargs["seed"] == llm_client.EXTRACTION_SEED

    generate("p", model="other-model")
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "other-model"


def test_generate_none_content_returns_empty_string(fake_client):
    fake_client.chat.completions.create.return_value = _response(None)
    assert generate("p") == ""


def _finished(content, reason, completion_tokens=8192):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                 finish_reason=reason)],
        usage=SimpleNamespace(completion_tokens=completion_tokens),
    )


def test_generate_warns_when_reasoning_eats_the_whole_budget(fake_client, caplog):
    """qwen3.8-27b in thinking mode answers HTTP 200, finish=length, no content.

    Measured on tei 2026-09-21: 8192 tokens of reasoning, 0 characters of
    transcription. Nothing raises, so without this warning the empty answer
    is indistinguishable from a blank page — and it must not be retried.
    """
    fake_client.chat.completions.create.return_value = _finished(None, "length")
    with caplog.at_level(logging.WARNING, logger="llm_client"):
        assert generate("p", model="qwen3.8-27b") == ""
    assert "qwen3.8-27b stopped at the token limit (8192" in caplog.text
    assert "enable_thinking=false" in caplog.text
    assert fake_client.chat.completions.create.call_count == 1


def test_generate_warns_on_truncated_content(fake_client, caplog):
    fake_client.chat.completions.create.return_value = _finished("partial", "length")
    with caplog.at_level(logging.WARNING, logger="llm_client"):
        assert generate("p") == "partial"
    assert "with 7 chars of content" in caplog.text
    assert "enable_thinking" not in caplog.text


def test_generate_is_quiet_on_a_normal_stop(fake_client, caplog):
    fake_client.chat.completions.create.return_value = _finished("done", "stop", 3)
    with caplog.at_level(logging.WARNING, logger="llm_client"):
        assert generate("p") == "done"
    assert caplog.records == []


def test_generate_retries_transient_failures(fake_client):
    fake_client.chat.completions.create.side_effect = [
        RuntimeError("boom"),
        _response("recovered"),
    ]
    assert generate("p") == "recovered"
    assert fake_client.chat.completions.create.call_count == 2


def test_generate_raises_after_max_attempts(fake_client):
    fake_client.chat.completions.create.side_effect = RuntimeError("down")
    with pytest.raises(RuntimeError, match="down"):
        generate("p")
    assert fake_client.chat.completions.create.call_count == 3


def test_with_retry_backoff_is_exponential(monkeypatch):
    delays = []
    monkeypatch.setattr(llm_client.time, "sleep", delays.append)

    calls = {"n": 0}

    @with_retry(max_attempts=3, base_delay=2.0)
    def flaky():
        calls["n"] += 1
        raise ValueError("always")

    with pytest.raises(ValueError):
        flaky()
    assert calls["n"] == 3
    assert delays == [2.0, 4.0]


# ── GPUStack SSE-framed JSON (regression since 16./17.10.2026) ──────────────
#
# Measured against gpustack.unibe.ch on 19.10.2026: ``stream=false`` returns
# ``content-type: application/json`` with the body ``data: {...}`` — one
# frame, no newline, no ``[DONE]`` — and gzip-encoded when the client
# accepts it.

import gzip
import json

import openai

httpx = llm_client.httpx  # the SDK's own httpx (httpx or httpx2)

_COMPLETION = {
    "id": "chatcmpl-x", "object": "chat.completion", "created": 1, "model": "m",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "OK"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _gpustack(body: bytes, ctype="application/json", gzipped=False):
    """A mock upstream that answers every POST with the given body."""
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"content-type": ctype}
        content = body
        if gzipped:
            content = gzip.compress(body)
            headers["content-encoding"] = "gzip"
        return httpx.Response(200, headers=headers, content=content)
    return httpx.MockTransport(handler)


def _client_over(transport: httpx.BaseTransport) -> openai.OpenAI:
    return openai.OpenAI(
        base_url="http://gpustack.test/v1", api_key="k", max_retries=0,
        http_client=openai.DefaultHttpxClient(transport=transport),
    )


def _ask(client: openai.OpenAI) -> str:
    resp = client.chat.completions.create(model="m", messages=[{"role": "user", "content": "p"}])
    return resp.choices[0].message.content


def test_sdk_fails_on_the_framed_body_without_the_fix():
    """Counter-test: the guard matters. The bare SDK chokes on ``data: {``.

    The nightly of 17./18.10.2026 named exactly this: ``JSONDecodeError``.
    """
    framed = b"data: " + json.dumps(_COMPLETION).encode()
    with pytest.raises((openai.APIError, json.JSONDecodeError)):
        _ask(_client_over(_gpustack(framed)))


def test_lenient_transport_strips_the_sse_frame(caplog):
    framed = b"data: " + json.dumps(_COMPLETION).encode()
    transport = llm_client.LenientJSONTransport(_gpustack(framed))
    with caplog.at_level(logging.WARNING, logger="llm_client"):
        assert _ask(_client_over(transport)) == "OK"
        assert _ask(_client_over(transport)) == "OK"
    assert transport.stripped == 2
    assert caplog.text.count("framed a non-streaming JSON reply") == 1


def test_lenient_transport_decodes_gzip_before_looking():
    framed = b"data: " + json.dumps(_COMPLETION).encode()
    transport = llm_client.LenientJSONTransport(_gpustack(framed, gzipped=True))
    assert _ask(_client_over(transport)) == "OK"
    assert transport.stripped == 1


def test_lenient_transport_leaves_clean_json_alone():
    transport = llm_client.LenientJSONTransport(_gpustack(json.dumps(_COMPLETION).encode()))
    assert _ask(_client_over(transport)) == "OK"
    assert transport.stripped == 0


def test_lenient_transport_leaves_event_streams_alone():
    """A real stream is ``text/event-stream``; its frames must survive."""
    chunk = {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "m",
             "choices": [{"index": 0, "delta": {"content": "OK"}, "finish_reason": None}]}
    body = b"data: " + json.dumps(chunk).encode() + b"\n\ndata: [DONE]\n\n"
    transport = llm_client.LenientJSONTransport(_gpustack(body, ctype="text/event-stream"))
    client = _client_over(transport)
    stream = client.chat.completions.create(
        model="m", messages=[{"role": "user", "content": "p"}], stream=True)
    assert [c.choices[0].delta.content for c in stream] == ["OK"]
    assert transport.stripped == 0


def test_get_client_uses_the_lenient_transport(monkeypatch):
    monkeypatch.setattr(llm_client, "_client", None)
    client = llm_client.get_client()
    assert isinstance(client._client._transport, llm_client.LenientJSONTransport)
