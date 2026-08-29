from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts.capabilities.adapters import (
    ATRAdapter,
    GPUStackAdapter,
    MCPAdapter,
    QLeverAdapter,
    RemoteToolAdapter,
    VoyantAdapter,
    default_registry,
)
from scripts.capabilities.contracts import (
    ArtifactRef,
    Availability,
    CapabilityDescriptor,
    CapabilityError,
    ToolSpec,
)
from scripts.capabilities.provenance import JsonlInvocationLog
from scripts.capabilities.registry import CapabilityRegistry

ROOT = Path(__file__).parents[1]


def response(status: int = 200, payload=None, *, headers=None) -> httpx.Response:
    request = httpx.Request("GET", "https://provider.test")
    return httpx.Response(status, json=payload, headers=headers, request=request)


class FakeAdapter:
    def __init__(self, cap_id: str, *, required=False, enabled=True, status="available"):
        self.descriptor = CapabilityDescriptor(
            cap_id,
            "fake",
            "fake-contract",
            "1",
            required,
            enabled,
            (ToolSpec("fake.run", "run", {}, {}),),
        )
        self.status = status

    def discover(self):
        return Availability(self.descriptor.id, self.status, "now", provider_version="v1")

    def invoke(self, tool_id, arguments):
        if arguments.get("fail"):
            raise RuntimeError("provider failed")
        return {"ok": True}


def test_registry_blocks_missing_required_but_surfaces_optional() -> None:
    registry = CapabilityRegistry()
    registry.register(FakeAdapter("required", required=True, status="unavailable"))
    registry.register(FakeAdapter("optional", status="unavailable"))
    registry.register(FakeAdapter("disabled", enabled=False))
    report = registry.discover()
    assert report["status"] == "fail"
    assert report["errors"] == ["required capability required: unavailable"]
    assert {item["capability_id"]: item["status"] for item in report["capabilities"]} == {
        "disabled": "disabled",
        "optional": "unavailable",
        "required": "unavailable",
    }


def test_invocation_log_records_refs_not_arguments_or_payload(tmp_path: Path) -> None:
    log_path = tmp_path / "invocations.jsonl"
    registry = CapabilityRegistry(invocation_log=JsonlInvocationLog(log_path))
    registry.register(FakeAdapter("cap"))
    registry.discover()
    result = registry.invoke(
        "cap",
        "fake.run",
        {"source_text": "PRIVATE", "api_key": "NEVER-LOG"},
        run_id="run-1",
        inputs=[ArtifactRef("urn:input", "a" * 64)],
        output_refs=[ArtifactRef("urn:output", "b" * 64)],
    )
    assert result == {"ok": True}
    raw = log_path.read_text()
    assert "PRIVATE" not in raw and "NEVER-LOG" not in raw
    record = json.loads(raw)
    assert record["status"] == "success"
    assert record["inputs"][0]["sha256"] == "a" * 64


def test_failed_and_blocked_invocations_are_audited(tmp_path: Path) -> None:
    log_path = tmp_path / "invocations.jsonl"
    registry = CapabilityRegistry(invocation_log=JsonlInvocationLog(log_path))
    registry.register(FakeAdapter("failure"))
    registry.register(FakeAdapter("blocked", enabled=False))
    registry.discover()
    with pytest.raises(RuntimeError):
        registry.invoke("failure", "fake.run", {"fail": True}, run_id="run")
    with pytest.raises(CapabilityError):
        registry.invoke("blocked", "fake.run", {}, run_id="run")
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [item["status"] for item in records] == ["error", "blocked"]
    assert records[0]["error_type"] == "RuntimeError"


def test_gpustack_discovers_roles_and_routes_tools() -> None:
    seen = []

    def transport(method, url, **kwargs):
        seen.append((method, url, kwargs.get("json")))
        if method == "GET":
            return response(payload={"data": [{"id": name} for name in ("text", "vision", "orch", "embed", "rank")]})
        return response(payload={"ok": True})

    adapter = GPUStackAdapter(
        "https://gpu.test/v1",
        "credential",
        {"text": "text", "vision": "vision", "orchestrator": "orch", "embedding": "embed", "reranker": "rank"},
        transport=transport,
    )
    assert adapter.discover().status == "available"
    adapter.invoke("embedding.embed", {"input": ["a"]})
    adapter.invoke("reranker.rerank", {"query": "q", "documents": ["a"]})
    adapter.invoke("text.generate", {"messages": []})
    assert [item[1].rsplit("/", 1)[-1] for item in seen] == ["models", "embeddings", "rerank", "completions"]
    assert seen[-1][2]["model"] == "text"


def test_gpustack_reports_missing_configured_model() -> None:
    adapter = GPUStackAdapter(
        "https://gpu.test/v1",
        "credential",
        {"text": "text", "vision": "vision", "orchestrator": "orch"},
        transport=lambda *args, **kwargs: response(payload={"data": [{"id": "text"}]}),
    )
    result = adapter.discover()
    assert result.status == "incompatible"
    assert "orch" in result.detail


class FakeAtrClient:
    base_url = "http://atr.test"

    def health_check(self):
        return {"version": "1.2"}

    def list_models(self):
        return [{"id": "kraken"}]

    def segment(self, image, seg_mode="baseline"):
        return {"lines": [], "mode": seg_mode}

    def transcribe(self, image, model, engine="kraken", seg_mode="baseline"):
        return SimpleNamespace(
            text="text", confidence=0.9, model=model, engine=engine, service_version="1.2"
        )


def test_atr_shim_preserves_attributed_result() -> None:
    adapter = ATRAdapter(FakeAtrClient(), enabled=True)
    assert adapter.discover().provider_version == "1.2"
    result = adapter.invoke("atr.ocr", {"image": b"image", "model": "kraken"})
    assert result == {
        "text": "text",
        "confidence": 0.9,
        "model": "kraken",
        "engine": "kraken",
        "service_version": "1.2",
    }
    recognized = adapter.invoke("atr.recognize", {"image": b"image", "model": "party-model"})
    assert recognized["engine"] == "party"


def test_mcp_initializes_discovers_and_maps_candidates_without_merging() -> None:
    calls = []

    def transport(method, url, **kwargs):
        payload = kwargs["json"]
        calls.append(payload["method"])
        if payload["method"] == "initialize":
            return response(payload={"jsonrpc": "2.0", "id": 1, "result": {}}, headers={"Mcp-Session-Id": "s"})
        if payload["method"] == "tools/list":
            return response(payload={"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "search_persons"}]}})
        return response(status=202, payload={})

    adapter = MCPAdapter("https://mcp.test/mcp", enabled=True, transport=transport)
    availability = adapter.discover()
    assert availability.tools == ("search_persons",)
    assert calls == ["initialize", "notifications/initialized", "tools/list"]
    candidates = adapter.to_outremer_candidates(
        {"persons": [{"source": "hls", "pid": "42", "name": "Anna", "wikidata_id": "Q1"}]}
    )
    assert candidates == [
        {
            "candidate_id": "mcp:hls:42",
            "label": "Anna",
            "source": "hls",
            "source_id": "42",
            "variants": [],
            "external_ids": {"wikidata_id": "Q1"},
            "status": "unreviewed",
        }
    ]


def test_qlever_is_read_only_even_after_prefix() -> None:
    adapter = QLeverAdapter(
        "https://qlever.test/query",
        enabled=True,
        transport=lambda *args, **kwargs: response(payload={"boolean": True}),
    )
    assert adapter.discover().status == "available"
    assert adapter.invoke("graph.query", {"query": "ASK { ?s ?p ?o }"}) == {"boolean": True}
    with pytest.raises(CapabilityError, match="update"):
        adapter.invoke("graph.query", {"query": "PREFIX x: <urn:x> DELETE WHERE { ?s ?p ?o }"})


def test_voyant_requires_explicit_nonempty_text() -> None:
    seen = []

    def transport(method, url, **kwargs):
        seen.append((method, kwargs.get("data")))
        return response(payload={}, headers={"Location": "https://voyant.test/?corpus=1"})

    adapter = VoyantAdapter("https://voyant.test", enabled=True, transport=transport)
    assert adapter.discover().status == "available"
    with pytest.raises(CapabilityError):
        adapter.invoke("corpus.handoff", {"text": " "})
    result = adapter.invoke("corpus.handoff", {"text": "approved corpus"})
    assert result["location"].endswith("corpus=1")
    assert seen[-1] == ("POST", {"text": "approved corpus"})


def test_remote_tools_are_discovered_not_hardcoded() -> None:
    def transport(method, url, **kwargs):
        if method == "GET":
            return response(
                payload={
                    "version": "2",
                    "tools": [
                        {
                            "id": "source.describe",
                            "description": "describe",
                            "input_schema": {"type": "object"},
                            "output_schema": {"type": "object"},
                        }
                    ],
                }
            )
        return response(payload={"artifact": "urn:result"})

    adapter = RemoteToolAdapter("https://tools.test", enabled=True, transport=transport)
    assert adapter.discover().tools == ("source.describe",)
    assert adapter.invoke("source.describe", {"artifact": "urn:source"}) == {"artifact": "urn:result"}

    registry = CapabilityRegistry(audit_required=False)
    registry.register(RemoteToolAdapter("https://tools.test", enabled=True, transport=transport))
    assert registry.invoke(
        "agent-tools", "source.describe", {"artifact": "urn:source"}, run_id="run"
    ) == {"artifact": "urn:result"}


def test_registry_refuses_unaudited_invocation() -> None:
    registry = CapabilityRegistry()
    registry.register(FakeAdapter("cap"))
    with pytest.raises(CapabilityError, match="audit log"):
        registry.invoke("cap", "fake.run", {}, run_id="run")


def test_artifact_refs_require_real_digests() -> None:
    with pytest.raises(ValueError, match="sha256"):
        ArtifactRef("urn:artifact", "not-a-digest")


def test_adapter_package_does_not_import_agentic_historian_internals() -> None:
    imports = []
    for path in (ROOT / "scripts/capabilities").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
    assert not any(name == "agentic_historian" or name.startswith("agentic_historian.") for name in imports)


@pytest.mark.live_backend
@pytest.mark.skipif(
    os.environ.get("OUTREMER_LIVE_CAPABILITY_SMOKE") != "1",
    reason="set on the protected university runner only",
)
def test_live_shared_capability_discovery() -> None:
    report = default_registry().discover()
    by_id = {item["capability_id"]: item["status"] for item in report["capabilities"]}
    assert all(by_id.get(capability) == "available" for capability in ("gpustack", "atr", "mcp", "qlever", "voyant"))
