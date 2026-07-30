import json
import xml.etree.ElementTree as ET
from pathlib import Path

from rdflib import Graph

from scripts.evidence_model import canonical_bytes
from scripts.evidence_publish import (
    discovery_projection,
    graph_to_dataset,
    publication_graph,
    publish,
    tei_standoff,
)
from scripts.evidence_review import append_review, make_review, review_state

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "evidence-first" / "representative.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_jsonld_and_turtle_round_trip_without_semantic_loss():
    original = fixture()
    graph = publication_graph(original)
    for format_name in ("json-ld", "turtle"):
        serialized = graph.serialize(format=format_name)
        restored_graph = Graph().parse(data=serialized, format=format_name)
        restored = graph_to_dataset(restored_graph)
        assert canonical_bytes(restored) == canonical_bytes({
            "schema_version": original["schema_version"],
            "objects": sorted(original["objects"], key=lambda obj: obj["id"]),
        })


def test_profiles_publish_all_expected_outputs(tmp_path):
    paths = publish(fixture(), tmp_path)
    assert set(paths) == {"canonical", "jsonld", "turtle", "discovery", "tei"}
    assert all(path.exists() and path.stat().st_size for path in paths.values())


def test_schema_org_is_explicitly_lossy_discovery_projection():
    projection = discovery_projection(fixture())
    assert projection["@context"] == "https://schema.org"
    assert "Lossy discovery projection" in projection["description"]
    assert all(item["@id"].startswith("https://outremer.example/id/") for item in projection["hasPart"])


def test_tei_links_mentions_without_embedding_graph():
    xml = tei_standoff(fixture())
    root = ET.fromstring(xml)
    spans = root.findall(".//{http://www.tei-c.org/ns/1.0}span")
    assert {span.text for span in spans} == {"Baldwin", "the pilgrims"}
    baldwin = next(span for span in spans if span.text == "Baldwin")
    assert baldwin.attrib["ref"].endswith("/person/baldwin-i")
    assert "canonicalJson" not in xml


def test_reviews_are_append_only_pseudonymous_and_commentable(tmp_path):
    review = make_review(
        target_id="outremer:assertion:participation-1",
        target_type="assertion",
        action="flag",
        reviewer="private-user-id",
        comment="Contradicts the second passage.",
        timestamp="2026-07-26T10:00:00Z",
    )
    path = tmp_path / "reviews.jsonl"
    append_review(path, review)
    assert "private-user-id" not in path.read_text(encoding="utf-8")
    assert review["reviewer"].startswith("reviewer-")
    assert review["comment"]


def test_concurrent_reviewer_disagreement_remains_visible():
    target = "outremer:identity_hypothesis:baldwin"
    accept = make_review(
        target_id=target, target_type="identity_hypothesis", action="accept",
        reviewer="a", comment="", timestamp="2026-07-26T10:00:00Z",
    )
    reject = make_review(
        target_id=target, target_type="identity_hypothesis", action="reject",
        reviewer="b", comment="Chronology", timestamp="2026-07-26T10:01:00Z",
    )
    state = review_state([accept, reject], target)
    assert state["conflict"] is True
    assert len(state["active"]) == 2


def test_supersede_preserves_prior_review_history():
    target = "outremer:assertion:participation-1"
    first = make_review(
        target_id=target, target_type="assertion", action="accept",
        reviewer="a", comment="", timestamp="2026-07-26T10:00:00Z",
    )
    replacement = make_review(
        target_id=target, target_type="assertion", action="supersede",
        reviewer="a", comment="New evidence", supersedes=first["id"],
        timestamp="2026-07-26T11:00:00Z",
    )
    state = review_state([first, replacement], target)
    assert len(state["history"]) == 2
    assert state["active"] == [replacement]


def test_review_ui_exposes_all_required_actions():
    html = (ROOT / "site" / "evidence-review.html").read_text(encoding="utf-8")
    script = (
        (ROOT / "site" / "evidence-review.js").read_text(encoding="utf-8")
        + (ROOT / "site" / "evidence-review-core.mjs").read_text(encoding="utf-8")
    )
    assert "identity_hypothesis" in script and "assertion" in script
    for action in ("accept", "reject", "flag", "supersede"):
        assert action in script
    assert "comment" in script and "conflict" in script
    assert "evidence-review.js" in html


def test_existing_decisions_file_is_not_a_publication_or_review_target():
    sources = (
        (ROOT / "scripts" / "evidence_publish.py").read_text(encoding="utf-8")
        + (ROOT / "scripts" / "evidence_review.py").read_text(encoding="utf-8")
    )
    assert "data/decisions.json" not in sources
