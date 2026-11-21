"""Offline tests for the MCP federation row mapping (M21.3, #127, Teil 1).

Row fixtures are real rows observed from the tei MCP fleet's
``search_persons`` tools (hls, ssrq, kf).
"""

from __future__ import annotations

import json

import pytest

from scripts.capabilities.contracts import CapabilityError
from scripts.capabilities.mcp_federation import BUILTIN_MAPPERS, extract_rows

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
