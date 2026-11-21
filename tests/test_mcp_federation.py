"""Offline tests for the MCP federation adapter (M21.3, #127).

Row fixtures are real rows observed from the tei MCP fleet's
``search_persons`` tools (hls, ssrq, kf); every transport is mocked.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from scripts.capabilities.adapters import default_registry
from scripts.capabilities.contracts import CapabilityError
from scripts.capabilities.mcp_federation import (
    BUILTIN_MAPPERS,
    InstitutionSource,
    MCPFederationAdapter,
    build_federation_from_env,
    extract_rows,
)

ROOT = Path(__file__).parents[1]

HLS_ROW = {
    "id": "per-011912",
    "article_id": "011912",
    "family_name": "Haller",
    "first_name": "Adolf",
    "additional": "",
    "birth_date": "1897-10-15",
    "death_date": "1970-09-21",
    "gender": "m",
    "title": "Adolf Haller",
    "category": "bio",
    "lexical_class": ["Person"],
    "lat": 0.0,
    "lon": 0.0,
}
SSRQ_ROW = {
    "id": "per024893",
    "label": "David Haller",
    "std_name": "David Haller",
    "forename": "David",
    "surname": "",
    "sex": "1",
    "first_year": 1664,
    "last_year": 1664,
    "years": "[1664]",
    "orig_names": '["David", "NN"]',
}
KF_ROW = {
    "id": "per029544",
    "forename": "Berthold",
    "surname": "Haller",
    "main_name": "Berthold Haller",
    "occupation": None,
    "birth": "1611",
    "death": "1659",
    "hls_id": None,
}


def fleet_result(rows: list[dict], *, is_error: bool = False, structured: bool = True) -> dict:
    """The tools/call result shape the fleet actually sends (SSE-decoded JSON)."""
    result: dict = {
        "content": [
            {"type": "text", "text": json.dumps(row, indent=2, ensure_ascii=False)} for row in rows
        ],
        "isError": is_error,
    }
    if structured:
        result["structuredContent"] = {"result": rows}
    return result


def make_transport(routes: dict[str, dict]):
    """host -> {"rows": [...], "tools": [...], "status": int}; unlisted hosts get 404."""
    calls: list[tuple[str, str]] = []

    def transport(method: str, url: str, **kwargs) -> httpx.Response:
        host = httpx.URL(url).host
        calls.append((method, host))
        spec = routes.get(host, {"status": 404})
        status = spec.get("status", 200)
        if status != 200:
            return httpx.Response(status, text="unavailable", request=httpx.Request(method, url))
        payload = kwargs.get("json") or {}
        name = payload.get("method")
        if name == "tools/list":
            body = {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"tools": [{"name": t} for t in spec.get("tools", ["search_persons"])]},
            }
        elif name == "tools/call":
            body = {
                "jsonrpc": "2.0",
                "id": 2,
                "result": spec.get("call_result", fleet_result(spec.get("rows", []))),
            }
        else:  # initialize, notifications/initialized
            body = {"jsonrpc": "2.0", "id": 1, "result": {}}
        return httpx.Response(
            200, json=body, headers={"Mcp-Session-Id": "sess"}, request=httpx.Request(method, url)
        )

    return transport, calls


def build_federated(names=("hls", "ssrq", "kf"), routes: dict[str, dict] | None = None):
    transport, calls = make_transport(routes or {})
    sources = tuple(
        InstitutionSource(name, f"http://{name}.test/mcp/{name}/mcp", BUILTIN_MAPPERS[name])
        for name in names
    )
    return MCPFederationAdapter(sources, enabled=True, transport=transport), calls


def test_hls_row_maps_to_unreviewed_candidate_with_source_id() -> None:
    candidate = BUILTIN_MAPPERS["hls"](HLS_ROW)
    assert candidate is not None
    assert candidate["candidate_id"] == "mcp:hls:per-011912"
    assert candidate["label"] == "Adolf Haller"
    assert candidate["source"] == "hls"
    assert candidate["source_id"] == "per-011912"
    assert candidate["status"] == "unreviewed"
    assert candidate["external_ids"] == {"hls_id": "per-011912"}
    assert candidate["variants"] == []


def test_hls_row_adds_name_combinations_as_variants() -> None:
    row = dict(
        HLS_ROW,
        id="per-012345",
        first_name="Emil",
        family_name="Hodler",
        additional="jun.",
        title="Emil Hodler jun.",
    )
    candidate = BUILTIN_MAPPERS["hls"](row)
    assert candidate is not None
    assert candidate["label"] == "Emil Hodler jun."
    assert candidate["variants"] == ["Emil Hodler"]


def test_ssrq_row_parses_orig_names_json_string_and_drops_placeholder() -> None:
    candidate = BUILTIN_MAPPERS["ssrq"](SSRQ_ROW)
    assert candidate is not None
    assert candidate["candidate_id"] == "mcp:ssrq:per024893"
    assert candidate["label"] == "David Haller"
    assert candidate["variants"] == ["David"]
    assert candidate["external_ids"] == {}


def test_kf_row_carries_source_id_and_omits_null_hls_id() -> None:
    candidate = BUILTIN_MAPPERS["kf"](KF_ROW)
    assert candidate is not None
    assert candidate["candidate_id"] == "mcp:kf:per029544"
    assert candidate["label"] == "Berthold Haller"
    assert candidate["variants"] == []
    assert candidate["external_ids"] == {}
    linked = dict(KF_ROW, hls_id="per-006857")
    assert BUILTIN_MAPPERS["kf"](linked)["external_ids"] == {"hls_id": "per-006857"}


def test_rows_without_id_are_dropped() -> None:
    assert BUILTIN_MAPPERS["hls"]({"title": "Nameless"}) is None
    assert BUILTIN_MAPPERS["ssrq"]({"label": "Nameless"}) is None
    assert BUILTIN_MAPPERS["kf"]({"main_name": "Nameless"}) is None


def test_extract_rows_uses_structured_content_of_the_live_envelope() -> None:
    rows = [
        SSRQ_ROW,
        dict(
            SSRQ_ROW,
            id="per001778",
            label="Emmanuel D. von Haller",
            std_name="Emmanuel D. von Haller",
        ),
    ]
    assert extract_rows(fleet_result(rows)) == rows


def test_extract_rows_falls_back_to_content_text_blocks() -> None:
    rows = [SSRQ_ROW, KF_ROW]
    assert extract_rows(fleet_result(rows, structured=False)) == rows


def test_extract_rows_treats_is_error_as_error_not_empty() -> None:
    with pytest.raises(CapabilityError, match="isError"):
        extract_rows(fleet_result([], is_error=True, structured=False))


def test_extract_rows_accepts_bare_list_and_result_field() -> None:
    assert extract_rows([SSRQ_ROW]) == [SSRQ_ROW]
    assert extract_rows({"result": [SSRQ_ROW]}) == [SSRQ_ROW]
    assert extract_rows({}) == []


def test_fanout_merges_all_institutions_with_source_ids() -> None:
    fed, calls = build_federated(
        routes={
            "hls.test": {"rows": [HLS_ROW]},
            "ssrq.test": {"rows": [SSRQ_ROW]},
            "kf.test": {"rows": [KF_ROW]},
        }
    )
    out = fed.invoke("federation.person_search", {"query": "Haller", "limit": 5})
    assert out["failures"] == []
    assert [item["candidate_id"] for item in out["candidates"]] == [
        "mcp:hls:per-011912",
        "mcp:ssrq:per024893",
        "mcp:kf:per029544",
    ]
    assert all(item["status"] == "unreviewed" for item in out["candidates"])
    assert {host for _, host in calls} == {"hls.test", "ssrq.test", "kf.test"}


def test_same_name_from_two_sources_stays_two_candidates() -> None:
    hls_same_person = dict(
        HLS_ROW, id="per-000042", title="David Haller", first_name="David", family_name="Haller"
    )
    fed, _ = build_federated(
        routes={
            "hls.test": {"rows": [hls_same_person]},
            "ssrq.test": {"rows": [SSRQ_ROW]},
            "kf.test": {"rows": []},
        }
    )
    out = fed.invoke("federation.person_search", {"query": "Haller"})
    assert [item["label"] for item in out["candidates"]] == ["David Haller", "David Haller"]
    assert {item["source"] for item in out["candidates"]} == {"hls", "ssrq"}
    assert len({item["candidate_id"] for item in out["candidates"]}) == 2


def test_partial_failure_returns_remaining_sources_and_names_the_failure() -> None:
    fed, _ = build_federated(
        routes={
            "hls.test": {"rows": [HLS_ROW], "status": 500},
            "ssrq.test": {"rows": [SSRQ_ROW]},
            "kf.test": {"rows": []},
        }
    )
    out = fed.invoke("federation.person_search", {"query": "Haller"})
    assert [item["candidate_id"] for item in out["candidates"]] == ["mcp:ssrq:per024893"]
    assert out["failures"] == [
        {"source": "hls", "error": "CapabilityError: provider returned HTTP 500"}
    ]


def test_all_sources_failing_is_an_error() -> None:
    fed, _ = build_federated(
        routes={
            "hls.test": {"status": 500},
            "ssrq.test": {"status": 502},
            "kf.test": {"status": 404},
        }
    )
    with pytest.raises(CapabilityError, match="all MCP federation sources failed"):
        fed.invoke("federation.person_search", {"query": "Haller"})


def test_empty_result_is_not_a_failure() -> None:
    fed, _ = build_federated(
        routes={"hls.test": {"rows": []}, "ssrq.test": {"rows": []}, "kf.test": {"rows": []}}
    )
    assert fed.invoke("federation.person_search", {"query": "unfindable"}) == {
        "candidates": [],
        "failures": [],
    }


def test_invoke_requires_query_and_known_tool() -> None:
    fed, calls = build_federated(routes={"hls.test": {"rows": []}})
    with pytest.raises(CapabilityError, match="query"):
        fed.invoke("federation.person_search", {"query": "  "})
    with pytest.raises(CapabilityError, match="no tool"):
        fed.invoke("mcp.person_search", {"query": "Haller"})
    assert calls == []


def test_discover_reports_per_source_and_requires_search_persons() -> None:
    fed, _ = build_federated(
        routes={
            "hls.test": {"rows": []},
            "ssrq.test": {"rows": [], "tools": ["describe_source"]},
            "kf.test": {"rows": [], "status": 500},
        }
    )
    availability = fed.discover()
    assert availability.status == "available"
    assert availability.capability_id == "mcp-federation"
    assert availability.tools == ("federation.person_search",)
    assert "sources ok: hls" in (availability.detail or "")
    assert "ssrq" in (availability.detail or "") and "does not expose search_persons" in (
        availability.detail or ""
    )
    assert "kf" in (availability.detail or "")


def test_discover_unavailable_when_no_source_works() -> None:
    fed, _ = build_federated(
        routes={
            "hls.test": {"status": 500},
            "ssrq.test": {"status": 500},
            "kf.test": {"status": 500},
        }
    )
    availability = fed.discover()
    assert availability.status == "unavailable"
    assert availability.detail.count("failed") == 1


def test_discover_reports_missing_configuration() -> None:
    fed = MCPFederationAdapter(
        (),
        enabled=True,
        transport=lambda *args, **kwargs: httpx.Response(
            200, json={}, request=httpx.Request("POST", "http://unused.test")
        ),
    )
    availability = fed.discover()
    assert availability.status == "unavailable"
    assert availability.detail == "no sources configured"


def test_base_url_drives_endpoints_and_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_BASE_URL", "https://tei.dh.unibe.ch")
    monkeypatch.setenv("MCP_FEDERATION_SOURCES", "hls,ssrq,kf")
    monkeypatch.setenv("MCP_FEDERATION_KF_URL", "http://127.0.0.1:8123/mcp")
    monkeypatch.setenv("MCP_FEDERATION_HLS_AUTH", "Basic dGVzdA==")
    monkeypatch.setenv("OUTREMER_CAPABILITY_MCP_FEDERATION", "1")
    fed = build_federation_from_env()
    by_name = {source.name: source for source in fed.sources}
    assert {name: source.endpoint for name, source in by_name.items()} == {
        "hls": "https://tei.dh.unibe.ch/mcp/hls/mcp",
        "ssrq": "https://tei.dh.unibe.ch/mcp/ssrq/mcp",
        "kf": "http://127.0.0.1:8123/mcp",
    }
    assert by_name["hls"].authorization == "Basic dGVzdA=="
    assert by_name["ssrq"].authorization == ""
    assert fed.descriptor.enabled is True


def test_source_requests_hit_the_endpoint_without_trailing_slash() -> None:
    """The fleet answers POST /mcp/<name>/mcp but 307-redirects the
    trailing-slash variant; MCP posts must use the configured endpoint as-is."""
    seen: list[str] = []

    def transport(method: str, url: str, **kwargs) -> httpx.Response:
        seen.append(url)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {}}, request=httpx.Request(method, url)
        )

    fed = MCPFederationAdapter(
        (InstitutionSource("ssrq", "http://fleet.test/mcp/ssrq/mcp", BUILTIN_MAPPERS["ssrq"]),),
        enabled=True,
        transport=transport,
    )
    try:
        fed.discover()
    except CapabilityError:
        pass
    assert seen and all(url == "http://fleet.test/mcp/ssrq/mcp" for url in seen)


def test_authorization_header_sent_by_source_adapter() -> None:
    seen: list[dict] = []

    def transport(method: str, url: str, **kwargs) -> httpx.Response:
        seen.append(kwargs.get("headers") or {})
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {}}, request=httpx.Request(method, url)
        )

    fed = MCPFederationAdapter(
        (
            InstitutionSource(
                "hls",
                "http://hls.test/mcp/hls/mcp",
                BUILTIN_MAPPERS["hls"],
                authorization="Basic dGVzdA==",
            ),
        ),
        enabled=True,
        transport=transport,
    )
    try:
        fed.discover()
    except CapabilityError:
        pass
    assert seen and all(item.get("Authorization") == "Basic dGVzdA==" for item in seen)


def test_unknown_source_name_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_BASE_URL", "https://tei.dh.unibe.ch")
    monkeypatch.setenv("MCP_FEDERATION_SOURCES", "hls,eos")
    with pytest.raises(CapabilityError, match="no row mapper"):
        build_federation_from_env()


def test_default_off_registers_disabled_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "OUTREMER_CAPABILITY_MCP_FEDERATION",
        "MCP_BASE_URL",
        "MCP_FEDERATION_SOURCES",
    ):
        monkeypatch.delenv(variable, raising=False)
    for name in ("HLS", "SSRQ", "KF"):
        monkeypatch.delenv(f"MCP_FEDERATION_{name}_URL", raising=False)
        monkeypatch.delenv(f"MCP_FEDERATION_{name}_AUTH", raising=False)
    report = default_registry().discover()
    by_id = {item["capability_id"]: item["status"] for item in report["capabilities"]}
    assert by_id["mcp-federation"] == "disabled"


def test_federation_module_imports_nothing_beyond_capabilities_and_stdlib() -> None:
    """The adapter layer stays provider-neutral (see the package import test)."""
    import ast

    source = (ROOT / "scripts/capabilities/mcp_federation.py").read_text()
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import inside scripts/capabilities
                modules.append("." * node.level + (node.module or ""))
            elif node.module:
                modules.append(node.module)
    allowed = ("__future__", "json", "os", "collections.abc", "dataclasses", "datetime", "typing")
    assert all(
        name in allowed or name.startswith(".") or name.startswith("scripts.capabilities")
        for name in modules
    )


@pytest.mark.live_backend
@pytest.mark.skipif(
    os.environ.get("OUTREMER_LIVE_CAPABILITY_SMOKE") != "1",
    reason="set on the protected university runner only",
)
def test_live_federation_reaches_the_fleet(monkeypatch: pytest.MonkeyPatch) -> None:
    if not os.environ.get("MCP_BASE_URL"):
        pytest.skip("MCP_BASE_URL not configured")
    fed = build_federation_from_env()
    availability = fed.discover()
    assert availability.status == "available", availability.detail
    out = fed.invoke("federation.person_search", {"query": "Haller", "limit": 3})
    assert out["candidates"], out["failures"]
    assert all(item["status"] == "unreviewed" and item["source_id"] for item in out["candidates"])
