"""Offline tests for the ATR gateway client."""

import httpx
import pytest
from atr_client import AtrClient, AtrClientError


def _client(handler, *, api_key="secret", timeout=300):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url="https://atr.example",
        headers={"X-API-Key": api_key},
        timeout=timeout,
        transport=transport,
    )
    return AtrClient(
        "https://atr.example",
        api_key=api_key,
        timeout=timeout,
        http_client=http,
    )


def test_health_and_models_contract_with_api_key():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"models": [{"id": "kraken-a"}]})

    client = _client(handler)
    assert client.health_check() == {"status": "ok"}
    assert client.list_models() == [{"id": "kraken-a"}]
    assert [request.url.path for request in seen] == ["/health", "/models"]
    assert all(request.headers["X-API-Key"] == "secret" for request in seen)


def test_segment_posts_image_and_mode(tmp_path):
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"image")

    def handler(request):
        body = request.read()
        assert request.url.path == "/segment"
        assert b"page.png" in body
        assert b"baseline" in body
        return httpx.Response(200, json={"lines": [{"baseline": [[0, 0], [1, 1]]}]})

    client = _client(handler)
    result = client.segment(image_path, seg_mode="baseline")
    assert len(result["lines"]) == 1


def test_transcribe_uses_ocr_for_kraken_and_recognize_for_party():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "text": "transcription",
                "confidence": 0.9,
                "model": "model-a",
                "version": "1.2",
            },
        )

    client = _client(handler)
    kraken = client.transcribe(b"image", model="model-a", engine="kraken")
    party = client.transcribe(b"image", model="model-b", engine="party")
    assert paths == ["/ocr", "/recognize"]
    assert kraken.text == "transcription"
    assert kraken.confidence == 0.9
    assert kraken.service_version == "1.2"
    assert party.engine == "party"


def test_transcribe_rejects_engine_not_supported_by_ocr():
    client = _client(lambda _request: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="kraken and trocr"):
        client.transcribe(b"image", model="x", engine="unknown")


def test_http_error_is_actionable():
    client = _client(
        lambda _request: httpx.Response(422, text="invalid multipart payload")
    )
    with pytest.raises(AtrClientError, match="422.*invalid multipart"):
        client.segment(b"image")


def test_default_timeout_matches_gateway_engine_budget(monkeypatch):
    import atr_client

    monkeypatch.setattr(atr_client, "ATR_HTTP_TIMEOUT", 300)
    client = AtrClient("https://atr.example")
    assert client.timeout == 300
