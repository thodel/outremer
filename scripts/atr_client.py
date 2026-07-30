"""Client for the serving-atr-inference recognition gateway.

The gateway exposes health/model discovery plus segmentation and recognition:
``GET /health``, ``GET /models``, and ``POST /segment``, ``/recognize``,
``/ocr``. Every authenticated request carries ``X-API-Key``.

``/ocr`` auto-segments page images and accepts kraken and TrOCR engines.
The page-level ``party`` engine must use ``/recognize``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from config import ATR_API_KEY, ATR_GATEWAY_URL, ATR_HTTP_TIMEOUT


class AtrClientError(RuntimeError):
    """Raised when the ATR gateway is unreachable or rejects a request."""


@dataclass(frozen=True)
class AtrResult:
    """Attributed recognition result returned by the ATR gateway."""

    text: str
    confidence: float
    model: str
    engine: str
    service_version: str = "?"


class AtrClient:
    """Thin synchronous client for serving-atr-inference."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else ATR_GATEWAY_URL).rstrip("/")
        self.api_key = ATR_API_KEY if api_key is None else api_key
        self.timeout = ATR_HTTP_TIMEOUT if timeout is None else timeout
        self._client = http_client
        self._owns_client = http_client is None

    def __enter__(self) -> AtrClient:
        self._get_client()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the internally owned HTTP session, if one was created."""
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def health_check(self) -> dict[str, Any]:
        """Return gateway health and engine availability."""
        return self._request("GET", "/health").json()

    def list_models(self) -> list[dict[str, Any]]:
        """Return the gateway's attributed model registry."""
        models = self._request("GET", "/models").json().get("models", [])
        return models if isinstance(models, list) else []

    def segment(
        self,
        image: Path | bytes | io.BytesIO,
        *,
        seg_mode: str = "baseline",
    ) -> dict[str, Any]:
        """Segment a page without recognizing its text."""
        response = self._request(
            "POST",
            "/segment",
            files=self._image_part(image),
            data={"seg_mode": seg_mode},
        )
        return response.json()

    def recognize(
        self,
        image: Path | bytes | io.BytesIO,
        *,
        model: str,
        engine: str = "party",
    ) -> AtrResult:
        """Recognize a page through ``/recognize`` (required for party)."""
        response = self._request(
            "POST",
            "/recognize",
            files=self._image_part(image),
            data={"model": model},
        )
        return self._result(response, model=model, engine=engine)

    def transcribe(
        self,
        image: Path | bytes | io.BytesIO,
        *,
        model: str,
        engine: str = "kraken",
        seg_mode: str = "baseline",
    ) -> AtrResult:
        """Recognize a page, dispatching party to its required endpoint."""
        if engine.casefold() == "party":
            return self.recognize(image, model=model, engine=engine)
        if engine.casefold() not in {"kraken", "trocr"}:
            raise ValueError("ATR /ocr supports only kraken and trocr engines")
        response = self._request(
            "POST",
            "/ocr",
            files=self._image_part(image),
            data={"model": model, "seg_mode": seg_mode},
        )
        return self._result(response, model=model, engine=engine)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            if not self.base_url:
                raise AtrClientError(
                    "ATR gateway URL is not configured; set ATR_GATEWAY_URL"
                )
            headers = {"X-API-Key": self.api_key} if self.api_key else {}
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._get_client().request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise AtrClientError(
                f"ATR gateway unreachable at {self.base_url}{path}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise AtrClientError(
                f"ATR gateway returned {response.status_code} at {path}: "
                f"{response.text[:400]}"
            )
        return response

    @staticmethod
    def _image_part(
        image: Path | bytes | io.BytesIO,
    ) -> dict[str, tuple[str, bytes, str]]:
        if isinstance(image, Path):
            content = image.read_bytes()
            filename = image.name
        elif isinstance(image, bytes):
            content = image
            filename = "image"
        else:
            image.seek(0)
            content = image.read()
            filename = "image"
        return {"image": (filename, content, "application/octet-stream")}

    @staticmethod
    def _result(response: httpx.Response, *, model: str, engine: str) -> AtrResult:
        payload = response.json()
        return AtrResult(
            text=payload.get("text", ""),
            confidence=float(payload.get("confidence", 0.0)),
            model=payload.get("model", model),
            engine=payload.get("engine", engine),
            service_version=payload.get("version", "?"),
        )
