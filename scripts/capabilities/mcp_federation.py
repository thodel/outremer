"""MCP federation: the per-institution tei MCP fleet as unreviewed candidate source.

Epic 21 (M21.3, #127).  The tei MCP fleet exposes one MCP server per
institution (``https://tei.dh.unibe.ch/mcp/<name>/mcp``: hls, ssrq, kf, …);
each server carries its own ``search_persons`` tool and its own row shape.
This part (M21.3, Teil 1) provides the row mapping and the result-envelope
extraction; Teil 2 adds the registry adapter (``MCPFederationAdapter``), the
environment build and the airgap allowlist.  The candidate mapping reuses the
never merged into authority truth.  The empty/error distinction required by
ADR 0001 is explicit: per-source failures are reported in the result, and the
call is an error only when every source fails.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .contracts import CapabilityError

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
