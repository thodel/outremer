"""M21.2 (#126): the reranker vetoes, never reorders; OFF is byte-identical."""

import json

import pytest
import reranker
from linker import build_authority_lookup, link_voyagers_to_outremer

INDEX = {"persons": [
    {"authority_id": "AUTH:CR185", "preferred_label": "Robert II of Flanders", "type": "person",
     "name": {"name": "Robert", "regnal": "II", "toponym": "Flanders"},
     "variants": ["Count Robert of Flanders", "Robert II de Flandre"],
     "identifiers": {"wikidata_qid": "Q333306"}},
    {"authority_id": "AUTH:CR56", "preferred_label": "Robert of Milly", "type": "person",
     "name": {"name": "Robert", "toponym": "Milly"}, "variants": ["Robert (Milly)"], "identifiers": {}},
]}
PERSONS = [
    {"name": "Count Robert of Flanders", "context": "Count Robert of Flanders was treated for the rest of his life"},
    {"name": "Robert of Sourdeval", "context": "Richard of the Principality, Robert of Sourdeval, Robert fitzTristan"},
    {"name": "Nobody Known", "context": ""},
]


def _conf(min_relevance=0.25):
    return {"base_url": "http://127.0.0.1:9", "api_key": "x", "model": "test-reranker",
            "min_relevance": min_relevance, "context_chars": 300, "timeout": 1, "snapshot": None}


def test_off_is_byte_identical(monkeypatch):
    monkeypatch.delenv("OUTREMER_CAPABILITY_RERANKER", raising=False)
    lookup = build_authority_lookup(INDEX)
    monkeypatch.setattr(reranker, "rerank", lambda *a, **k: pytest.fail("reranker must not be called when OFF"))
    a = json.dumps(link_voyagers_to_outremer(PERSONS, lookup), sort_keys=True)
    b = json.dumps(link_voyagers_to_outremer(PERSONS, lookup, rerank=False), sort_keys=True)
    assert a == b
    assert "rerank" not in a


def test_veto_turns_an_unfitting_top_into_no_match_but_keeps_the_candidates():
    lookup = build_authority_lookup(INDEX)
    # floor 0.60 so that the namesake mention gets a fuzzy candidate at all
    links = link_voyagers_to_outremer(PERSONS, lookup, rerank=False, min_score=0.6)
    by = {lk["person"]: lk for lk in links}
    assert by["Robert of Sourdeval"]["top_candidate"] is not None   # the fuzzy linker proposes someone

    def fake(query, docs, conf):
        # the real reranker: a true match scores high, a namesake low
        return [0.55 if "Count Robert of Flanders" in query else 0.08 for _ in docs]

    summary = reranker.apply_veto(links, PERSONS, {p["authority_id"]: p for p in INDEX["persons"]},
                                  conf=_conf(), rerank_fn=fake)
    assert summary == {"model": "test-reranker", "min_relevance": 0.25, "checked": 2, "vetoed": 1, "errors": 0}
    kept = by["Count Robert of Flanders"]
    assert kept["status"] == "high" and kept["rerank"]["veto"] is False
    assert kept["candidates"][0]["relevance"] == 0.55
    vetoed = by["Robert of Sourdeval"]
    assert vetoed["status"] == "no_match" and vetoed["top_candidate"] is None and vetoed["confidence"] == 0.0
    assert vetoed["candidates"], "candidates stay visible for review"
    assert vetoed["rerank"] == {"model": "test-reranker", "top_relevance": 0.08, "min_relevance": 0.25, "veto": True}
    assert "rerank" not in by["Nobody Known"], "nothing to check without candidates"


def test_the_order_of_candidates_is_never_changed():
    lookup = build_authority_lookup(INDEX)
    links = link_voyagers_to_outremer(PERSONS, lookup, rerank=False)
    before = [[c["outremer_id"] for c in lk["candidates"]] for lk in links]
    reranker.apply_veto(links, PERSONS, {p["authority_id"]: p for p in INDEX["persons"]}, conf=_conf(),
                        rerank_fn=lambda q, d, c: [0.9] * len(d))
    assert [[c["outremer_id"] for c in lk["candidates"]] for lk in links] == before


def test_a_failing_reranker_leaves_the_fuzzy_links_and_says_so():
    lookup = build_authority_lookup(INDEX)
    links = link_voyagers_to_outremer(PERSONS, lookup, rerank=False, min_score=0.6)
    fuzzy = json.dumps([{k: v for k, v in lk.items() if k != "rerank"} for lk in links], sort_keys=True)

    def down(*a, **k):
        raise ConnectionError("refused")

    summary = reranker.apply_veto(links, PERSONS, {p["authority_id"]: p for p in INDEX["persons"]},
                                  conf=_conf(), rerank_fn=down)
    assert summary["errors"] == 2 and summary["vetoed"] == 0
    assert json.dumps([{k: v for k, v in lk.items() if k != "rerank"} for lk in links], sort_keys=True) == fuzzy
    assert links[0]["rerank"]["error"] == "refused"


def test_record_text_reads_name_facts_and_whole_name_forms():
    rec = INDEX["persons"][0]
    assert reranker.record_text(rec, "Count of Flanders (1065-1111). lived 1065–1111") == (
        "Robert II of Flanders. Count of Flanders (1065-1111). lived 1065–1111. "
        "toponym: Flanders. regnal: II. also Count Robert of Flanders; Robert II de Flandre")
    assert reranker.record_text({"preferred_label": "X", "variants": ["Bare"]}) == "X"


def test_enabled_reads_the_capability_flag(monkeypatch):
    monkeypatch.delenv("OUTREMER_CAPABILITY_RERANKER", raising=False)
    assert reranker.enabled() is False
    monkeypatch.setenv("OUTREMER_CAPABILITY_RERANKER", "true")
    assert reranker.enabled() is True
