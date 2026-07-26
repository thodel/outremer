import json
from pathlib import Path

from rdflib import Literal

from scripts.evidence_semantics import (
    OUT,
    assertion_from_graph,
    dataset_to_graph,
    uri,
    validate_graph,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "evidence-first" / "uncertainty.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_time_uncertainty_place_and_provenance_round_trip():
    data = fixture()
    graph = dataset_to_graph(data)
    restored = assertion_from_graph(graph, "outremer:assertion:uncertain-visit")
    source = next(obj for obj in data["objects"] if obj["type"] == "assertion")
    assert restored["semantics"] == source["semantics"]
    assert restored["asserted_time"] == source["asserted_time"]
    assert restored["place_candidates"] == source["place_candidates"]
    assert restored["provenance"]["snapshot_uri"].endswith("/snapshot/chronicle")
    assert restored["provenance"]["review_activity_uri"].endswith("/activity/review-3")


def test_date_bounds_survive_jsonld_and_turtle_serialization():
    source_graph = dataset_to_graph(fixture())
    for format_name in ("json-ld", "turtle"):
        serialized = source_graph.serialize(format=format_name)
        restored_graph = type(source_graph)().parse(data=serialized, format=format_name)
        restored = assertion_from_graph(
            restored_graph, "outremer:assertion:uncertain-visit"
        )
        assert restored["asserted_time"]["notBefore"] == 1160
        assert restored["asserted_time"]["notAfter"] == 1170
        assert "twentieth and thirtieth year" in restored["asserted_time"]["original_text"]
        assert "regnal dating" in restored["asserted_time"]["calendar_note"]


def test_source_assertion_ingestion_and_review_times_remain_distinct():
    data = fixture()
    snapshot = data["objects"][0]
    extraction = data["objects"][2]
    review = data["objects"][3]
    assertion = data["objects"][4]
    assert assertion["asserted_time"]["notBefore"] == 1160
    assert snapshot["source_created_at"].startswith("1175")
    assert snapshot["ingested_at"].startswith("2026-07-26T08")
    assert extraction["started_at"].startswith("2026-07-26T08")
    assert review["started_at"].startswith("2026-07-26T09")


def test_valid_fixture_conforms_to_shacl():
    conforms, report = validate_graph(dataset_to_graph(fixture()))
    assert conforms, report


def test_shacl_rejects_assertion_without_evidence():
    graph = dataset_to_graph(fixture())
    assertion = uri("outremer:assertion:uncertain-visit")
    graph.remove((assertion, OUT.evidencePassage, None))
    conforms, report = validate_graph(graph)
    assert not conforms
    assert "requires an evidence passage" in report


def test_shacl_rejects_malformed_range():
    graph = dataset_to_graph(fixture())
    assertion = uri("outremer:assertion:uncertain-visit")
    graph.set((assertion, OUT.notBefore, Literal(1200)))
    graph.set((assertion, OUT.notAfter, Literal(1100)))
    conforms, report = validate_graph(graph)
    assert not conforms
    assert "notBefore" in report


def test_shacl_rejects_untyped_decision_status():
    graph = dataset_to_graph(fixture())
    decision = uri("outremer:decision:identity-accepted")
    graph.set((decision, OUT.decisionStatus, Literal("maybe")))
    conforms, report = validate_graph(graph)
    assert not conforms
    assert "controlled vocabulary" in report


def test_shacl_rejects_accepted_decision_without_reviewer_provenance():
    graph = dataset_to_graph(fixture())
    activity = uri("outremer:activity:review-3")
    graph.remove((activity, OUT.responsibleAgent, None))
    conforms, report = validate_graph(graph)
    assert not conforms
    assert "require reviewer" in report


def test_all_competency_queries_parse_and_execute():
    graph = dataset_to_graph(fixture())
    for path in sorted((ROOT / "queries").glob("*.rq")):
        list(graph.query(path.read_text(encoding="utf-8")))
