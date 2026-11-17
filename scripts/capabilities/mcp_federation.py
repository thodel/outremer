"""MCP federation: the per-institution tei MCP fleet as unreviewed candidate source.

Epic 21 (M21.3, #127).  The tei MCP fleet exposes one MCP server per
institution (``https://tei.dh.unibe.ch/mcp/<name>/mcp``: hls, ssrq, kf, …);
each server carries its own ``search_persons`` tool and its own row shape.
Following the ch-h-bot MCP-per-institution ingestion contract, every
institution is a registry entry (name, endpoint, row mapping) and the
server's own tool discovery verifies the contract before a source counts as
available.  The candidate mapping reuses the anti-corruption shape from #120:
source-local ids (``per-…`` / ``per…``) ride along on every candidate and are
never merged into authority truth.  The empty/error distinction required by
ADR 0001 is explicit: per-source failures are reported in the result, and the
call is an error only when every source fails.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .adapters import MCPAdapter, Transport, checked_endpoint, enabled
from .contracts import Availability, CapabilityDescriptor, CapabilityError, ToolSpec

PERSON_SEARCH = "search_persons"
DEFAULT_SOURCES = "hls,ssrq,kf"

# "NN" is the sources' "not named" placeholder, not a name spelling.
_PLACEHOLDER = {"nn"}


def _parts(*values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _candidate(
    source: str, source_id: str, label: str, variants: list[str], external_ids: dict[str, Any]
) -> dict[str, Any]:
    """The #120 candidate shape: source ids ride along, never merged into authority truth."""
    return {
        "candidate_id": f"mcp:{source}:{source_id}",
        "label": label,
        "source": source,
        "source_id": source_id,
        "variants": variants,
        "external_ids": dict(external_ids),
        "status": "unreviewed",
    }


def _map_hls_row(row: dict[str, Any]) -> dict[str, Any] | None:
    source_id = str(row.get("id") or "")
    if not source_id:
        return None
    first, family, additional = (
        str(row.get(key) or "") for key in ("first_name", "family_name", "additional")
    )
    label = str(row.get("title") or "").strip() or " ".join(
        p for p in (first, family, additional) if p.strip()
    )
    if not label:
        return None
    combos: list[str] = []
    if first and family:
        combos.append(f"{first} {family}")
        if additional.strip():
            combos.append(f"{first} {family} {additional}".strip())
    variants = [part for part in _parts(*combos) if part != label]
    return _candidate("hls", source_id, label, variants, {"hls_id": source_id})


def _parse_orig_names(value: Any) -> list[str]:
    """SSRQ stores ``orig_names`` as a JSON-encoded string (``"[\"David\", \"NN\"]"``)."""
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        items = decoded if isinstance(decoded, list) else [decoded]
    else:
        return []
    names: list[str] = []
    for item in items:
        name = str(item or "").strip()
        if name and name.casefold() not in _PLACEHOLDER and name not in names:
            names.append(name)
    return names


def _map_ssrq_row(row: dict[str, Any]) -> dict[str, Any] | None:
    source_id = str(row.get("id") or "")
    if not source_id:
        return None
    label = (
        str(row.get("label") or row.get("std_name") or "").strip()
        or f"{row.get('forename') or ''} {row.get('surname') or ''}".strip()
    )
    if not label:
        return None
    variants = [
        part
        for part in _parts(
            *_parse_orig_names(row.get("orig_names")), str(row.get("std_name") or "").strip()
        )
        if part != label
    ]
    return _candidate("ssrq", source_id, label, variants, {})


def _map_kf_row(row: dict[str, Any]) -> dict[str, Any] | None:
    source_id = str(row.get("id") or "")
    if not source_id:
        return None
    forename, surname = (
        str(row.get("forename") or "").strip(),
        str(row.get("surname") or "").strip(),
    )
    label = str(row.get("main_name") or "").strip() or f"{forename} {surname}".strip()
    if not label:
        return None
    variants = [part for part in _parts(f"{forename} {surname}".strip()) if part != label]
    external_ids = {"hls_id": str(row["hls_id"])} if row.get("hls_id") is not None else {}
    return _candidate("kf", source_id, label, variants, external_ids)


BUILTIN_MAPPERS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] = {
    "hls": _map_hls_row,
    "ssrq": _map_ssrq_row,
    "kf": _map_kf_row,
}


def _parse_json_text(text: str) -> list[dict[str, Any]] | None:
    """A fleet text block: a JSON object, a JSON array, or ``{"result": rows}``."""
    text = text.strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        rows: list[dict[str, Any]] = []
        decoder = json.JSONDecoder()
        pos = 0
        while pos < len(text):
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if pos >= len(text):
                break
            obj, pos = decoder.raw_decode(text, pos)
            if not isinstance(obj, dict):
                raise CapabilityError("MCP federation text content is not a JSON object stream")
            rows.append(obj)
        return rows or None
    if isinstance(decoded, list):
        return [row for row in decoded if isinstance(row, dict)] or None
    if isinstance(decoded, dict):
        inner = decoded.get("result")
        if isinstance(inner, list):
            return [row for row in inner if isinstance(row, dict)] or None
        if isinstance(inner, str):
            return _parse_json_text(inner)
        return [decoded]  # the block carries the row itself
    return None


def extract_rows(result: Any) -> list[dict[str, Any]]:
    """Rows from a fleet ``search_persons`` tools/call result.

    The fleet sends the rows in ``structuredContent.result`` and, per row, as
    text blocks; both encodings are accepted.  An explicit ``isError`` is an
    error, never an empty result (ADR 0001).
    """
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if not isinstance(result, dict):
        return []
    if result.get("isError"):
        message = next(
            (
                block["text"][:200]
                for block in result.get("content") or []
                if isinstance(block, dict) and block.get("text")
            ),
            "",
        )
        raise CapabilityError(f"MCP federation search failed: {message or 'isError'}")
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and isinstance(structured.get("result"), list):
        return [row for row in structured["result"] if isinstance(row, dict)]
    rows: list[dict[str, Any]] = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            rows.extend(_parse_json_text(block["text"]) or [])
    if rows:
        return rows
    direct = result.get("result")
    if isinstance(direct, list):
        return [row for row in direct if isinstance(row, dict)]
    if isinstance(direct, str):
        return _parse_json_text(direct) or []
    return []


@dataclass(frozen=True)
class InstitutionSource:
    """One registry entry of the fleet: name, endpoint, row mapping (ch-h-bot pattern).

    ``authorization`` is a complete ``Authorization`` header value
    (``"Basic …"`` or ``"Bearer …"``); the fleet's hls server challenges with
    ``Basic realm="HLS MCP"`` while ssrq and kf answer without authentication.
    """

    name: str
    endpoint: str
    mapper: Callable[[dict[str, Any]], dict[str, Any] | None]
    authorization: str = ""


class MCPFederationAdapter:
    """Per-institution MCP sources as one unreviewed candidate source."""

    CONTRACT_VERSION = "2024-11-05"

    def __init__(
        self,
        sources: tuple[InstitutionSource, ...],
        *,
        enabled: bool = False,
        transport: Transport | None = None,
    ) -> None:
        self.sources = sources
        self.transport = transport
        self.descriptor = CapabilityDescriptor(
            "mcp-federation",
            "tei-mcp-fleet",
            "mcp-streamable-http",
            self.CONTRACT_VERSION,
            False,
            enabled,
            (
                ToolSpec(
                    "federation.person_search",
                    "search_persons across the configured institutions; unreviewed candidates with source ids",
                    {"type": "object"},
                    {"type": "object"},
                ),
            ),
        )

    def _source_adapter(self, source: InstitutionSource) -> MCPAdapter:
        return MCPAdapter(
            source.endpoint, authorization=source.authorization, transport=self.transport
        )

    def discover(self) -> Availability:
        ok: list[str] = []
        failures: list[str] = []
        for source in self.sources:
            try:
                availability = self._source_adapter(source).discover()
                if PERSON_SEARCH not in availability.tools:
                    raise CapabilityError(f"does not expose {PERSON_SEARCH}")
                ok.append(source.name)
            except Exception as exc:
                failures.append(f"{source.name}: {type(exc).__name__}: {exc}")
        if not self.sources:
            detail = "no sources configured"
        else:
            detail = f"sources ok: {', '.join(ok) or 'none'}"
            if failures:
                detail += f"; failed: {'; '.join(failures)}"
        return Availability(
            self.descriptor.id,
            "available" if ok else "unavailable",
            datetime.now(timezone.utc).isoformat(),
            provider_version=self.CONTRACT_VERSION,
            tools=tuple(tool.id for tool in self.descriptor.tools),
            detail=detail,
        )

    def invoke(self, tool_id: str, arguments: dict[str, Any]) -> Any:
        if tool_id != "federation.person_search":
            raise CapabilityError(f"mcp-federation has no tool {tool_id}")
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise CapabilityError("federation.person_search requires a non-empty query")
        limit = int(arguments.get("limit") or 10)
        candidates: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for source in self.sources:
            try:
                raw = self._source_adapter(source).invoke(
                    "mcp.person_search", {"query": query, "limit": limit}
                )
                for row in extract_rows(raw):
                    candidate = source.mapper(row)
                    if candidate is not None:
                        candidates.append(candidate)
            except Exception as exc:
                failures.append({"source": source.name, "error": f"{type(exc).__name__}: {exc}"})
        if self.sources and len(failures) == len(self.sources):
            raise CapabilityError(
                "all MCP federation sources failed: "
                + "; ".join(f"{item['source']} ({item['error']})" for item in failures)
            )
        return {"candidates": candidates, "failures": failures}


def build_federation_from_env() -> MCPFederationAdapter:
    """The federation strictly from the environment (README: Permitted network hosts).

    ``MCP_BASE_URL`` is the fleet base (endpoints ``…/mcp/<name>/mcp``);
    ``MCP_FEDERATION_<NAME>_URL`` overrides one institution (loopback on tei)
    and ``MCP_FEDERATION_<NAME>_AUTH`` carries that institution's complete
    ``Authorization`` header value.  A configured institution without a row
    mapping is a configuration error, not a guess.
    """
    base = os.environ.get("MCP_BASE_URL", "").rstrip("/")
    names: list[str] = []
    for name in os.environ.get("MCP_FEDERATION_SOURCES", DEFAULT_SOURCES).split(","):
        name = name.strip()
        if name and name not in names:
            names.append(name)
    sources: list[InstitutionSource] = []
    for name in names:
        endpoint = os.environ.get(f"MCP_FEDERATION_{name.upper()}_URL", "") or (
            f"{base}/mcp/{name}/mcp" if base else ""
        )
        if not endpoint:
            continue
        mapper = BUILTIN_MAPPERS.get(name)
        if mapper is None:
            raise CapabilityError(
                f"MCP federation source '{name}' has no row mapper; "
                f"known: {', '.join(sorted(BUILTIN_MAPPERS))}"
            )
        authorization = os.environ.get(f"MCP_FEDERATION_{name.upper()}_AUTH", "")
        sources.append(InstitutionSource(name, checked_endpoint(endpoint), mapper, authorization))
    return MCPFederationAdapter(
        tuple(sources), enabled=enabled("OUTREMER_CAPABILITY_MCP_FEDERATION")
    )
