"""Unit tests for scripts/llm_client.py — mocked client, no network.

The manual smoke test against the real GPUStack endpoint lives in
scripts/test_llm_client.py; these tests cover the retry/backoff and
message-building logic offline.
"""

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
    assert kwargs["model"] == llm_client.EXTRACTION_MODEL

    generate("p", model="other-model")
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "other-model"


def test_generate_none_content_returns_empty_string(fake_client):
    fake_client.chat.completions.create.return_value = _response(None)
    assert generate("p") == ""


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
