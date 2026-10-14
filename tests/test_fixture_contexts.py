"""M21.4 (#128): fixtures carry mention contexts, and ``--relink --rerank``
runs the reranker veto over them — while plain ``--relink`` stays offline and
byte-identical to the fuzzy linker."""

import json

import pytest
import reranker

from evaluation import harness
from evaluation.build_fixture import build_fixtures

INDEX_PERSONS = [
    {"authority_id": "AUTH:CR185", "preferred_label": "Robert II of Flanders", "type": "person",
     "name": {"name": "Robert", "regnal": "II", "toponym": "Flanders"},
     "variants": ["Count Robert of Flanders"], "identifiers": {}},
    {"authority_id": "AUTH:CR56", "preferred_label": "Robert of Milly", "type": "person",
     "name": {"name": "Robert", "toponym": "Milly"}, "variants": ["Robert (Milly)"], "identifiers": {}},
]
SITE_DOC = {
    "doc_id": "doc-a",
    "persons": [
        {"name": "Count Robert of Flanders", "context": "Count Robert of Flanders took the cross"},
        {"name": "Robert of Sourdeval", "context": "Robert of Sourdeval, Robert fitzTristan"},
        {"name": "Nameless", "context": ""},
    ],
    "links": [],
}
DECISIONS = [
    {"doc_id": "doc-a", "person": "Count Robert of Flanders", "outremer_id": "AUTH:CR185", "decision": "accept"},
    {"doc_id": "doc-a", "person": "Robert of Sourdeval", "outremer_id": "AUTH:CR56", "decision": "reject"},
]


@pytest.fixture
def site(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "doc-a.json").write_text(json.dumps(SITE_DOC))
    (tmp_path / "decisions.json").write_text(json.dumps(DECISIONS))
    return tmp_path


def test_build_fixture_keeps_each_mentions_context_keyed_by_name(site):
    (fx,) = build_fixtures(site / "decisions.json", site / "data")
    assert fx["predictions"]["persons"] == ["Count Robert of Flanders", "Robert of Sourdeval", "Nameless"]
    assert fx["predictions"]["contexts"] == {
        "Count Robert of Flanders": "Count Robert of Flanders took the cross",
        "Robert of Sourdeval": "Robert of Sourdeval, Robert fitzTristan",
    }, "empty contexts are not carried"


def _fixture():
    return {
        "doc_id": "doc-a", "mode": "adjudicated",
        "accepted": [["Count Robert of Flanders", "AUTH:CR185"]],
        "rejected": [["Robert of Sourdeval", "AUTH:CR56"]],
        "predictions": {
            "persons": ["Count Robert of Flanders", "Robert of Sourdeval"],
            "contexts": {"Count Robert of Flanders": "Count Robert of Flanders took the cross",
                         "Robert of Sourdeval": "Robert of Sourdeval, Robert fitzTristan"},
            "links": [],
        },
    }


@pytest.fixture
def small_authority(monkeypatch):
    import linker

    from evaluation import _pipeline

    monkeypatch.setattr(_pipeline, "load_authority_lookup",
                        lambda: linker.build_authority_lookup({"persons": INDEX_PERSONS}))
    # at floor 0.6 the namesake gets Robert of Milly as a candidate (score 0.60),
    # so the veto has something to judge; at the production floor it would not
    monkeypatch.setattr(linker, "LINK_CANDIDATE_FLOOR", 0.6)


def test_relink_alone_never_calls_the_reranker_even_when_the_flag_is_on(monkeypatch, small_authority):
    monkeypatch.setenv("OUTREMER_CAPABILITY_RERANKER", "true")
    monkeypatch.setattr(reranker, "apply_veto",
                        lambda *a, **k: pytest.fail("--relink without --rerank must stay offline"))
    res = harness.evaluate_fixture(_fixture(), relink=True)
    assert "reranker" not in res
    assert res["linking"]["accept_hit"] == 1


def test_relink_with_rerank_vetoes_in_context_and_reports_it(monkeypatch, small_authority):
    seen = {}

    def fake(query, docs, conf):
        seen[query] = docs
        return [0.6 if query.startswith("Count Robert of Flanders") else 0.05 for _ in docs]

    real = reranker.apply_veto
    monkeypatch.setattr(reranker, "apply_veto", lambda links, persons, records, **k: real(
        links, persons, records, rerank_fn=fake,
        conf={"base_url": "", "api_key": "", "model": "t", "min_relevance": 0.25,
              "context_chars": 300, "timeout": 1, "snapshot": None}))
    res = harness.evaluate_fixture(_fixture(), relink=True, rerank=True)
    assert res["reranker"] == {"checked": 2, "vetoed": 1, "errors": 0}
    # the veto saw the mention *with* its fixture context
    assert "Robert of Sourdeval. Robert of Sourdeval, Robert fitzTristan" in seen
    # and the judged-wrong namesake no longer counts as a proposal
    assert res["linking"]["accept_hit"] == 1 and res["linking"]["reject_avoided"] == 1


def test_rerank_requires_relink(capsys):
    with pytest.raises(SystemExit):
        harness.main(["--rerank"])
    assert "--rerank requires --relink" in capsys.readouterr().err
