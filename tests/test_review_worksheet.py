"""Tests for scripts/build_review_worksheet.py (#98 / #36 gold repair)."""

import json

from build_review_worksheet import (
    adjudicated_keys,
    build_growth_section,
    build_repair_section,
    collect_accepts,
)

DECISIONS = [
    # accepted, wrong-person pair (the #98 case)
    {"doc_id": "doc1", "person": "Albert of Aachen", "outremer_id": "AUTH:CR124",
     "decision": "accept", "client_id": "a"},
    # rejected pair — must not appear in the repair section
    {"doc_id": "doc1", "person": "Someone", "outremer_id": "AUTH:CR9",
     "decision": "reject", "client_id": "a"},
    # wikidata pair — different system, out of scope here
    {"doc_id": "doc1", "person": "Godfrey", "outremer_id": "wikidata:Q76721",
     "decision": "accept", "client_id": "a"},
]

DOCS = {
    "doc1": {
        "doc_id": "doc1",
        "persons": [
            {"name": "Tancred", "context": "Tancred marched south", "confidence": 0.8},
        ],
        "links": [
            {"person": "Tancred", "confidence": 0.95, "status": "high",
             "top_candidate": {"outremer_id": "AUTH:CR86", "outremer_name": "Tancred"},
             "candidates": [{"outremer_id": "AUTH:CR86", "outremer_name": "Tancred",
                             "score": 0.95}]},
            {"person": "Someone", "confidence": 0.7, "status": "medium",
             "top_candidate": {"outremer_id": "AUTH:CR9", "outremer_name": "Nine"},
             "candidates": []},
        ],
    }
}

AUTHORITY = {
    "AUTH:CR124": {"authority_id": "AUTH:CR124", "preferred_label": "Henry of Limal",
                   "variants": ["Henry", "Henry of Limal"]},
    "AUTH:CR86": {"authority_id": "AUTH:CR86", "preferred_label": "Tancred"},
}


def test_collect_accepts_only_authority_accepts():
    accepts = collect_accepts(DECISIONS)
    ids = {a["authority_id"] for a in accepts}
    assert ids == {"AUTH:CR124"}, "rejects and wikidata pairs must be excluded"


def test_repair_section_flags_name_mismatch():
    md = "\n".join(build_repair_section(collect_accepts(DECISIONS), DOCS, AUTHORITY))
    assert "Albert of Aachen" in md
    assert "Henry of Limal" in md
    assert "name mismatch" in md


def test_repair_section_flags_unextracted_mention():
    """Albert of Aachen is not in DOCS persons — reviewer must be told."""
    md = "\n".join(build_repair_section(collect_accepts(DECISIONS), DOCS, AUTHORITY))
    assert "no longer extracted" in md


def test_growth_section_excludes_already_reviewed():
    reviewed = adjudicated_keys(DECISIONS)
    md = "\n".join(build_growth_section(DOCS, reviewed, queue_size=10))
    # Tancred is unreviewed → queued; "Someone" was rejected → excluded
    assert "Tancred" in md
    assert "AUTH:CR9" not in md


def test_growth_section_respects_queue_size():
    md = "\n".join(build_growth_section(DOCS, set(), queue_size=1))
    assert md.count("| 1 |") == 1
    assert "| 2 |" not in md


def test_adjudicated_keys_normalises_whitespace():
    """decisions.json contains names like 'Miles of \\n Clermont'."""
    keys = adjudicated_keys(
        [{"doc_id": "d", "person": "Miles of \n Clermont",
          "outremer_id": "AUTH:CR115", "decision": "reject"}]
    )
    assert ("d", "miles of clermont", "AUTH:CR115") in keys


def test_worksheet_end_to_end(tmp_path):
    """The generator writes a worksheet with both parts."""
    import build_review_worksheet as bw

    dec = tmp_path / "decisions.json"
    dec.write_text(json.dumps(DECISIONS))
    site = tmp_path / "site"
    site.mkdir()
    (site / "doc1.json").write_text(json.dumps(DOCS["doc1"]))
    auth = tmp_path / "authority.json"
    auth.write_text(json.dumps({"persons": list(AUTHORITY.values())}))
    out = tmp_path / "worksheet.md"

    rc = bw.main([
        "--decisions", str(dec), "--site-data", str(site),
        "--authority", str(auth), "--out", str(out),
    ])
    assert rc == 0
    text = out.read_text()
    assert "Part 1 — Repair" in text
    assert "Part 2 — Grow" in text
