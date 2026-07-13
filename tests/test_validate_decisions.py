"""Tests for scripts/validate_decisions.py — the schema validation M8.2 added.

Covers: valid files, missing required fields, unknown decision values,
conflicting multi-reviewer decisions, and non-list top-level payloads.
"""

import json

import pytest
from validate_decisions import (
    format_validation_report,
    validate_decisions_file,
)


def _write(tmp_path, payload):
    p = tmp_path / "decisions.json"
    p.write_text(json.dumps(payload))
    return p


def _entry(**overrides):
    base = {
        "doc_id": "doc-1",
        "person": "Miles of Clermont",
        "outremer_id": "AUTH:CR115",
        "decision": "accept",
        "client_id": "anon-abc",
        "submitted_at": "2026-02-22T20:07:38.155276",
        "comment": "",
    }
    base.update(overrides)
    return base


def test_valid_file_parses_all_records(tmp_path):
    path = _write(tmp_path, [_entry(), _entry(person="Peter the Hermit", decision="reject")])
    result = validate_decisions_file(path)
    assert result.total_entries == 2
    assert len(result.records) == 2
    assert not result.errors


def test_missing_required_fields_are_reported_not_swallowed(tmp_path):
    path = _write(tmp_path, [_entry(doc_id=""), _entry(person=None), _entry(decision="")])
    result = validate_decisions_file(path)
    fields = {e.field for e in result.errors}
    assert "doc_id" in fields
    assert "person" in fields
    assert "decision" in fields
    # invalid entries must not become records
    assert len(result.records) < 3


def test_unknown_decision_value_rejected(tmp_path):
    path = _write(tmp_path, [_entry(decision="maybe")])
    result = validate_decisions_file(path)
    assert any(e.field == "decision" for e in result.errors)
    assert not result.records


def test_conflicting_reviewers_surface_as_conflict(tmp_path):
    path = _write(
        tmp_path,
        [
            _entry(client_id="reviewer-a", decision="accept"),
            _entry(client_id="reviewer-b", decision="reject"),
        ],
    )
    result = validate_decisions_file(path)
    assert result.conflicts, "accept+reject on the same pair must be flagged"
    conflict = result.conflicts[0]
    assert "reviewer-a" in conflict.accepts
    assert "reviewer-b" in conflict.rejects


def test_non_list_payload_fails_loudly(tmp_path):
    path = _write(tmp_path, {"not": "a list"})
    result = validate_decisions_file(path)
    assert result.errors
    assert not result.records


def test_report_is_human_readable(tmp_path):
    path = _write(tmp_path, [_entry(), _entry(decision="bogus")])
    report = format_validation_report(validate_decisions_file(path))
    assert isinstance(report, str) and report.strip()


@pytest.mark.parametrize("decision", ["accept", "reject", "not_a_person", "wrong_era", "is_group"])
def test_all_documented_decision_values_accepted(tmp_path, decision):
    path = _write(tmp_path, [_entry(decision=decision)])
    result = validate_decisions_file(path)
    assert not result.errors, f"{decision} should be a valid decision"
