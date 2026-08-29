"""Anti-corruption adapters for the shared agentic-historian service stack."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .contracts import Availability, CapabilityDescriptor, CapabilityError, ToolSpec

Transport = Callable[..., httpx.Response]


def checked_endpoint(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CapabilityError("endpoint must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CapabilityError("endpoint cannot contain credentials, query, or fragment")
    return value.rstrip("/")


def checked(response: httpx.Response) -> httpx.Response:
    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise CapabilityError(f"provider returned HTTP {response.status_code}") from exc
    return response


def version(payload: Any, response: httpx.Response) -> str | None:
    if isinstance(payload, dict):
        for key in ("version", "service_version", "api_version"):
            if payload.get(key) is not None:
                return str(payload[key])
    return response.headers.get("X-Service-Version") or response.headers.get("X-API-Version")


def model_ids(payload: dict[str, Any]) -> set[str]:
    values = payload.get("data", payload.get("models", []))
    return {
        str(item.get("id") or item.get("name"))
        for item in values
        if isinstance(item, dict) and (item.get("id") or item.get("name"))
    }


class HttpAdapter:
    def __init__(self, endpoint: str, *, timeout: float = 30, transport: Transport | None = None) -> None:
        self.endpoint = checked_endpoint(endpoint) if endpoint else ""
        self.timeout = timeout
        self.transport = transport or httpx.request

    def request(self, method: str, path: str = "", **kwargs: Any) -> httpx.Response:
        if not self.endpoint:
            raise CapabilityError("endpoint is not configured")
        return checked(
            self.transport(method, f"{self.endpoint}/{path.lstrip('/')}", timeout=self.timeout, **kwargs)
        )

    def availability(
        self, descriptor: CapabilityDescriptor, response: httpx.Response, payload: Any
    ) -> Availability:
        return Availability(
            descriptor.id,
            "available",
            datetime.now(timezone.utc).isoformat(),
            provider_version=version(payload, response),
            endpoint=self.endpoint,
            tools=tuple(tool.id for tool in descriptor.tools),
        )


class GPUStackAdapter(HttpAdapter):
    CONTRACT_VERSION = "1.0"

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        models: dict[str, str],
        *,
        required: bool = True,
        enabled: bool = True,
        timeout: float = 120,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(endpoint, timeout=timeout, transport=transport)
        self.api_key = api_key
        self.models = models
        self.descriptor = CapabilityDescriptor(
            "gpustack",
            "unibe-gpustack",
            "openai-compatible",
            self.CONTRACT_VERSION,
            required,
            enabled,
            (
                ToolSpec("text.generate", "Role-routed text generation", {"type": "object"}, {"type": "object"}),
                ToolSpec("vision.generate", "Role-routed visual generation", {"type": "object"}, {"type": "object"}),
                ToolSpec("embedding.embed", "Multilingual embeddings", {"type": "object"}, {"type": "object"}),
                ToolSpec("reranker.rerank", "Multilingual candidate reranking", {"type": "object"}, {"type": "object"}),
            ),
        )

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise CapabilityError("GPUStack API key is not configured")
        return {"Authorization": f"Bearer {self.api_key}"}

    def discover(self) -> Availability:
        missing_roles = sorted(role for role in ("text", "vision", "orchestrator") if not self.models.get(role))
        if missing_roles:
            return Availability(
                self.descriptor.id,
                "incompatible",
                datetime.now(timezone.utc).isoformat(),
                endpoint=self.endpoint,
                detail=f"missing configured model role(s): {missing_roles}",
            )
        response = self.request("GET", "models", headers=self.headers)
        payload = response.json()
        available = model_ids(payload)
        required_models = {value for value in self.models.values() if value}
        missing = sorted(required_models - available)
        if missing:
            return Availability(
                self.descriptor.id,
                "incompatible",
                datetime.now(timezone.utc).isoformat(),
                endpoint=self.endpoint,
                detail=f"missing configured models: {missing}",
            )
        return self.availability(self.descriptor, response, payload)

    def invoke(self, tool_id: str, arguments: dict[str, Any]) -> Any:
        role_for_tool = {
            "text.generate": "text",
            "vision.generate": "vision",
            "embedding.embed": "embedding",
            "reranker.rerank": "reranker",
        }
        role = role_for_tool[tool_id]
        model = self.models.get(role)
        if not model:
            raise CapabilityError(f"no model configured for role {role}")
        if tool_id == "embedding.embed":
            payload = {"model": model, "input": arguments["input"]}
            return self.request("POST", "embeddings", headers=self.headers, json=payload).json()
        if tool_id == "reranker.rerank":
            payload = {"model": model, **arguments}
            return self.request("POST", "rerank", headers=self.headers, json=payload).json()
        payload = {"model": model, **arguments}
        return self.request("POST", "chat/completions", headers=self.headers, json=payload).json()


class ATRAdapter:
    """Temporary shim; #87 replaces the private client import with the shared package."""

    CONTRACT_VERSION = "1.0"

    def __init__(self, client: Any, *, required: bool = False, enabled: bool = True) -> None:
        self.client = client
        self.descriptor = CapabilityDescriptor(
            "atr",
            "serving-atr-inference",
            "atr-gateway",
            self.CONTRACT_VERSION,
            required,
            enabled,
            (
                ToolSpec("atr.segment", "Segment a page", {"type": "object"}, {"type": "object"}),
                ToolSpec("atr.recognize", "Recognize a page", {"type": "object"}, {"type": "object"}),
                ToolSpec("atr.ocr", "Segment and recognize a page", {"type": "object"}, {"type": "object"}),
            ),
        )

    def discover(self) -> Availability:
        health = self.client.health_check()
        models = self.client.list_models()
        return Availability(
            "atr",
            "available",
            datetime.now(timezone.utc).isoformat(),
            provider_version=str(health.get("version") or "unknown"),
            endpoint=getattr(self.client, "base_url", None),
            tools=tuple(tool.id for tool in self.descriptor.tools),
            detail=f"{len(models)} model(s)",
        )

    def invoke(self, tool_id: str, arguments: dict[str, Any]) -> Any:
        if tool_id == "atr.segment":
            return self.client.segment(arguments["image"], seg_mode=arguments.get("seg_mode", "baseline"))
        result = self.client.transcribe(
            arguments["image"],
            model=arguments["model"],
            engine=arguments.get("engine", "party" if tool_id == "atr.recognize" else "kraken"),
            seg_mode=arguments.get("seg_mode", "baseline"),
        )
        return {
            "text": result.text,
            "confidence": result.confidence,
            "model": result.model,
            "engine": result.engine,
            "service_version": result.service_version,
        }


class MCPAdapter(HttpAdapter):
    CONTRACT_VERSION = "2024-11-05"

    def __init__(self, endpoint: str, *, api_key: str = "", required: bool = False, enabled: bool = False, transport: Transport | None = None) -> None:
        super().__init__(endpoint, transport=transport)
        self.api_key = api_key
        self.descriptor = CapabilityDescriptor(
            "mcp",
            "agentic-historian-knowledge-hub",
            "mcp-streamable-http",
            self.CONTRACT_VERSION,
            required,
            enabled,
            (
                ToolSpec("mcp.person_search", "Federated person search", {"type": "object"}, {"type": "object"}),
                ToolSpec("mcp.source_description", "Provider source description", {"type": "object"}, {"type": "object"}),
            ),
        )

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        if "text/event-stream" in response.headers.get("content-type", ""):
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].lstrip())
            raise CapabilityError("MCP returned an empty event stream")
        return response.json()

    def _rpc(self, method: str, params: dict[str, Any], rpc_id: int = 2) -> tuple[httpx.Response, dict[str, Any]]:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": self.CONTRACT_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "outremer", "version": "0.1"},
            },
        }
        init_response = self.request("POST", "", headers=headers, json=initialize)
        init_body = self._decode(init_response)
        if init_body.get("error"):
            raise CapabilityError(f"MCP initialize error {init_body['error'].get('code')}")
        session = init_response.headers.get("Mcp-Session-Id")
        if session:
            headers["Mcp-Session-Id"] = session
        self.request(
            "POST",
            "",
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        payload = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        response = self.request("POST", "", headers=headers, json=payload)
        body = self._decode(response)
        if body.get("error"):
            raise CapabilityError(f"MCP error {body['error'].get('code')}")
        return response, body

    def discover(self) -> Availability:
        response, payload = self._rpc("tools/list", {})
        tools = payload.get("result", {}).get("tools", [])
        return Availability(
            "mcp",
            "available",
            datetime.now(timezone.utc).isoformat(),
            provider_version=response.headers.get("Mcp-Protocol-Version") or self.CONTRACT_VERSION,
            endpoint=self.endpoint,
            tools=tuple(sorted(str(tool.get("name")) for tool in tools if tool.get("name"))),
        )

    def invoke(self, tool_id: str, arguments: dict[str, Any]) -> Any:
        remote_name = {"mcp.person_search": "search_persons", "mcp.source_description": "describe_source"}[tool_id]
        _, payload = self._rpc("tools/call", {"name": remote_name, "arguments": arguments})
        return payload.get("result")

    @staticmethod
    def to_outremer_candidates(result: Any) -> list[dict[str, Any]]:
        """Preserve source identities; never merge them into authority truth."""
        persons = result.get("persons", []) if isinstance(result, dict) else []
        candidates = []
        for person in persons:
            source = str(person.get("source") or "unknown")
            pid = str(person.get("pid") or "")
            if not pid or not person.get("name"):
                continue
            candidates.append(
                {
                    "candidate_id": f"mcp:{source}:{pid}",
                    "label": str(person["name"]),
                    "source": source,
                    "source_id": pid,
                    "variants": list(person.get("variants") or []),
                    "external_ids": {
                        key: person[key]
                        for key in ("hls_id", "gnd_id", "wikidata_id")
                        if person.get(key) is not None
                    },
                    "status": "unreviewed",
                }
            )
        return candidates


class QLeverAdapter(HttpAdapter):
    CONTRACT_VERSION = "SPARQL-1.1"

    def __init__(self, endpoint: str, *, required: bool = False, enabled: bool = False, transport: Transport | None = None) -> None:
        super().__init__(endpoint, transport=transport)
        self.descriptor = CapabilityDescriptor(
            "qlever",
            "qlever",
            "sparql-query",
            self.CONTRACT_VERSION,
            required,
            enabled,
            (ToolSpec("graph.query", "Read-only SPARQL query", {"type": "object"}, {"type": "object"}),),
        )

    def discover(self) -> Availability:
        response = self.request(
            "POST", "", data={"query": "ASK { ?s ?p ?o }"}, headers={"Accept": "application/sparql-results+json"}
        )
        return self.availability(self.descriptor, response, response.json())

    def invoke(self, tool_id: str, arguments: dict[str, Any]) -> Any:
        query = str(arguments.get("query") or "").strip()
        if not query.casefold().startswith(("select", "ask", "construct", "describe", "prefix", "base")):
            raise CapabilityError("only read-only SPARQL queries are allowed")
        if re.search(r"\b(insert|delete|load|clear|create|drop|copy|move|add|with)\b", query, re.IGNORECASE):
            raise CapabilityError("SPARQL update operations are forbidden")
        return self.request(
            "POST", "", data={"query": query}, headers={"Accept": "application/sparql-results+json"}
        ).json()


class VoyantAdapter(HttpAdapter):
    CONTRACT_VERSION = "2.x"

    def __init__(self, endpoint: str, *, required: bool = False, enabled: bool = False, transport: Transport | None = None) -> None:
        super().__init__(endpoint, transport=transport)
        self.descriptor = CapabilityDescriptor(
            "voyant",
            "unibe-voyant",
            "voyant-corpus-handoff",
            self.CONTRACT_VERSION,
            required,
            enabled,
            (ToolSpec("corpus.handoff", "Upload an approved text corpus", {"type": "object"}, {"type": "object"}, mutating=True),),
        )

    def discover(self) -> Availability:
        response = self.request("GET", "")
        return self.availability(self.descriptor, response, None)

    def invoke(self, tool_id: str, arguments: dict[str, Any]) -> Any:
        text = arguments.get("text")
        if not isinstance(text, str) or not text.strip():
            raise CapabilityError("Voyant hand-off requires non-empty approved text")
        response = self.request("POST", "", data={"text": text})
        return {"location": response.headers.get("Location"), "status_code": response.status_code}


class RemoteToolAdapter(HttpAdapter):
    CONTRACT_VERSION = "1.0"

    def __init__(self, endpoint: str, *, enabled: bool = False, transport: Transport | None = None) -> None:
        super().__init__(endpoint, transport=transport)
        self._tools: tuple[ToolSpec, ...] = ()
        self.descriptor = self._descriptor(enabled)

    def _descriptor(self, enabled: bool) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            "agent-tools",
            "agentic-historian-tool-provider",
            "provider-neutral-tools",
            self.CONTRACT_VERSION,
            False,
            enabled,
            self._tools,
        )

    def discover(self) -> Availability:
        response = self.request("GET", "tools")
        payload = response.json()
        tools = []
        for item in payload.get("tools", []):
            tool_id = str(item.get("id") or item.get("name") or "")
            if not tool_id:
                continue
            tools.append(
                ToolSpec(
                    tool_id,
                    str(item.get("description") or ""),
                    dict(item.get("input_schema") or item.get("parameters") or {}),
                    dict(item.get("output_schema") or {}),
                    bool(item.get("mutating")),
                )
            )
        self._tools = tuple(tools)
        self.descriptor = self._descriptor(self.descriptor.enabled)
        return self.availability(self.descriptor, response, payload)

    def invoke(self, tool_id: str, arguments: dict[str, Any]) -> Any:
        return self.request("POST", "invoke", json={"tool": tool_id, "arguments": arguments}).json()


def enabled(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).casefold() in {"1", "true", "yes", "on"}


def default_registry(log_path: Path | None = None) -> Any:
    """Build adapters strictly from environment values, with no secret output."""
    try:
        from scripts.atr_client import AtrClient
    except ImportError:  # direct `python scripts/discover_capabilities.py`
        from atr_client import AtrClient

    from .provenance import JsonlInvocationLog
    from .registry import CapabilityRegistry

    registry = CapabilityRegistry(
        invocation_log=JsonlInvocationLog(log_path) if log_path is not None else None
    )
    models = {
        "text": os.environ.get("GPUSTACK_MODEL_TEXT") or os.environ.get("EXTRACTION_MODEL", ""),
        "vision": os.environ.get("GPUSTACK_MODEL_VISION") or os.environ.get("QWEN3_VL_MODEL", ""),
        "orchestrator": os.environ.get("GPUSTACK_MODEL_ORCHESTRATOR") or os.environ.get("ORCHESTRATOR_MODEL", ""),
        "embedding": os.environ.get("GPUSTACK_MODEL_EMBEDDING", ""),
        "reranker": os.environ.get("GPUSTACK_MODEL_RERANKER", ""),
    }
    registry.register(
        GPUStackAdapter(
            os.environ.get("GPUSTACK_BASE_URL", ""),
            os.environ.get("GPUSTACK_API_KEY", ""),
            models,
            required=True,
        )
    )
    atr_client = AtrClient(
        os.environ.get("ATR_GATEWAY_URL", ""),
        api_key=os.environ.get("ATR_API_KEY", ""),
    )
    registry.register(
        ATRAdapter(
            atr_client,
            required=enabled("OUTREMER_CAPABILITY_ATR_REQUIRED"),
            enabled=enabled("OUTREMER_CAPABILITY_ATR"),
        )
    )
    registry.register(
        MCPAdapter(
            os.environ.get("MCP_BASE_URL", ""),
            api_key=os.environ.get("MCP_API_KEY", ""),
            enabled=enabled("OUTREMER_CAPABILITY_MCP"),
        )
    )
    registry.register(QLeverAdapter(os.environ.get("QLEVER_ENDPOINT", ""), enabled=enabled("OUTREMER_CAPABILITY_QLEVER")))
    registry.register(VoyantAdapter(os.environ.get("VOYANT_API_URL", ""), enabled=enabled("OUTREMER_CAPABILITY_VOYANT")))
    registry.register(RemoteToolAdapter(os.environ.get("OUTREMER_TOOL_PROVIDER_URL", ""), enabled=enabled("OUTREMER_CAPABILITY_AGENT_TOOLS")))
    return registry
