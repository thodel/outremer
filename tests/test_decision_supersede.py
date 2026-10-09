"""M19.0 (#97): superseding adjudications and the `unresolved` verdict.

Historical decisions stay in the file; a later record flagged `supersedes`
retires them for its pair, and every consumer works on what is in force.
"""

import json

import pytest
from build_review_worksheet import adjudicated_keys, collect_accepts
from validate_decisions import (
    VALID_DECISIONS,
    effective_decisions,
    validate_decisions_file,
)

from evaluation.build_fixture import build_fixtures

WRONG_ACCEPT = {
    "doc_id": "doc1", "person": "Fulcher of Chartres", "outremer_id": "AUTH:CR33",
    "decision": "accept", "client_id": "anon-wrr096fimlxkf7sm",
    "submitted_at": "2026-02-28T14:15:26",
}
REPAIR = {
    "doc_id": "doc1", "person": "Fulcher of Chartres", "outremer_id": "AUTH:CR33",
    "decision": "reject", "client_id": "m19.0-repair", "supersedes": True,
    "comment": "wrong person: CR33 is Charles of Denmark",
    "submitted_at": "2026-10-09T20:00:00",
}
RETIRE = {
    "doc_id": "doc1", "person": "Peter", "outremer_id": "AUTH:CR53",
    "decision": "unresolved", "client_id": "m19.0-repair", "supersedes": True,
    "comment": "bare given name, context lost",
    "submitted_at": "2026-10-09T20:00:01",
}
PETER_ACCEPT = {
    "doc_id": "doc1", "person": "Peter", "outremer_id": "AUTH:CR53",
    "decision": "accept", "client_id": "anon-wrr096fimlxkf7sm",
    "submitted_at": "2026-02-28T13:50:18",
}
OTHER_REJECT = {
    "doc_id": "doc1", "person": "Someone", "outremer_id": "AUTH:CR9",
    "decision": "reject", "client_id": "a", "submitted_at": "2026-03-01T00:00:00",
}


def test_unresolved_is_a_valid_decision():
    assert "unresolved" in VALID_DECISIONS


def test_effective_decisions_retires_everything_before_the_superseding_record():
    kept = effective_decisions([WRONG_ACCEPT, PETER_ACCEPT, OTHER_REJECT, REPAIR, RETIRE])
    assert WRONG_ACCEPT not in kept and PETER_ACCEPT not in kept
    assert REPAIR in kept and RETIRE in kept and OTHER_REJECT in kept


def test_history_is_kept_in_the_file_but_not_in_force(tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps([WRONG_ACCEPT, REPAIR]))
    result = validate_decisions_file(path)
    assert not result.errors
    assert len(result.records) == 2, "the historical decision is preserved"
    assert result.conflicts == [], "a superseded accept does not conflict with the repair"


def test_superseding_needs_a_timestamp(tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps([{**REPAIR, "submitted_at": None}]))
    result = validate_decisions_file(path)
    assert any(e.field == "supersedes" for e in result.errors)


def test_without_supersedes_the_same_records_are_a_conflict(tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps([WRONG_ACCEPT, {**REPAIR, "supersedes": False}]))
    result = validate_decisions_file(path)
    assert len(result.conflicts) == 1


def test_fixture_builder_turns_the_repair_into_reject_gold_and_retires_unresolved(tmp_path):
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps([WRONG_ACCEPT, PETER_ACCEPT, OTHER_REJECT, REPAIR, RETIRE]))
    site = tmp_path / "site"
    site.mkdir()
    fixtures = build_fixtures(decisions, site)
    assert len(fixtures) == 1
    fx = fixtures[0]
    assert fx["accepted"] == []
    assert sorted(fx["rejected"]) == [["Fulcher of Chartres", "AUTH:CR33"], ["Someone", "AUTH:CR9"]]
    # Peter is in neither list: retired, not rejected.
    assert ["Peter", "AUTH:CR53"] not in fx["rejected"]


def test_worksheet_no_longer_lists_the_repaired_pair_and_keeps_retired_out_of_the_queue():
    decisions = [WRONG_ACCEPT, PETER_ACCEPT, REPAIR, RETIRE]
    assert collect_accepts(decisions) == []
    assert ("doc1", "peter", "AUTH:CR53") in adjudicated_keys(decisions)


@pytest.mark.parametrize("decision", sorted(VALID_DECISIONS))
def test_every_decision_value_validates(tmp_path, decision):
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps([{"doc_id": "d", "person": "p", "decision": decision}]))
    assert not validate_decisions_file(path).errors


def test_build_fixture_relink_uses_the_current_linker(tmp_path, monkeypatch):
    """--relink: persons and Wikidata stay as snapshotted, links are recomputed."""
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps([OTHER_REJECT]))
    site = tmp_path / "site"
    site.mkdir()
    (site / "doc1.json").write_text(json.dumps({
        "persons": [{"name": "Godfrey of Bouillon"}, {"name": "Someone"}],
        "links": [{"person": "Someone", "top_candidate": {"outremer_id": "AUTH:CR9"},
                   "candidates": []}],
    }))
    snapshot = build_fixtures(decisions, site)[0]["predictions"]["links"]
    assert snapshot == [{"person": "Someone", "top_candidate": {"outremer_id": "AUTH:CR9"},
                         "candidates": []}]
    relinked = build_fixtures(decisions, site, relink=True)[0]["predictions"]["links"]
    by_person = {link["person"]: link for link in relinked}
    assert set(by_person) == {"Godfrey of Bouillon", "Someone"}
    assert by_person["Godfrey of Bouillon"]["top_candidate"] == {"outremer_id": "AUTH:CR184"}
