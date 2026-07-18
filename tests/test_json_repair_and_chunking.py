"""Tests for the hardened LLM-output paths in scripts/extract_persons.py.

_repair_json, _recover_truncated_json, and _chunk_text shipped in Epic 2
without coverage; these are the paths that keep the pipeline alive when a
model returns malformed or truncated JSON.
"""

import json

from extract_persons import (
    _chunk_text,
    _recover_truncated_json,
    _repair_json,
)

# ── _repair_json ─────────────────────────────────────────────────────────────

def test_repair_strips_markdown_fences():
    raw = '```json\n{"persons": []}\n```'
    assert json.loads(_repair_json(raw)) == {"persons": []}


def test_repair_extracts_json_window_from_chatter():
    raw = 'Sure! Here is the JSON you asked for:\n{"persons": [{"name": "X"}]}\nHope this helps!'
    assert json.loads(_repair_json(raw))["persons"][0]["name"] == "X"


def test_repair_leaves_clean_json_intact():
    raw = '{"persons": [], "metadata": {"title": "T"}}'
    assert json.loads(_repair_json(raw)) == json.loads(raw)


# ── _recover_truncated_json ──────────────────────────────────────────────────

def test_recover_salvages_complete_persons_from_truncation():
    raw = (
        '{"persons": ['
        '{"name": "Godfrey of Bouillon", "confidence": 0.9},'
        '{"name": "Peter the Hermit", "confidence": 0.8},'
        '{"name": "Baldw'  # truncated mid-object
    )
    result = _recover_truncated_json(raw)
    names = [p.get("name") for p in result["persons"]]
    assert "Godfrey of Bouillon" in names
    assert "Peter the Hermit" in names
    assert all("Baldw" != n for n in names), "incomplete object must not be salvaged"


def test_recover_handles_input_without_persons_array():
    result = _recover_truncated_json("total garbage, no JSON at all")
    assert result == {"persons": [], "metadata": {}}


# ── _chunk_text ──────────────────────────────────────────────────────────────

def test_short_text_is_single_chunk():
    chunks = _chunk_text("short text", size=1000)
    assert chunks == [(0, "short text")]


def test_chunks_cover_all_paragraphs():
    paras = [f"Paragraph {i}. " + ("word " * 40).strip() for i in range(20)]
    text = "\n\n".join(paras)
    chunks = _chunk_text(text, size=800, overlap=100)
    assert len(chunks) > 1
    joined = " ".join(c for _, c in chunks)
    for i in range(20):
        assert f"Paragraph {i}." in joined, f"paragraph {i} lost in chunking"


def test_chunk_offsets_are_monotonic():
    text = "\n\n".join("para " + "x" * 300 for _ in range(10))
    chunks = _chunk_text(text, size=500, overlap=50)
    offsets = [off for off, _ in chunks]
    assert offsets == sorted(offsets)
    assert offsets[0] == 0
