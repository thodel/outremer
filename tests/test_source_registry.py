import json
from datetime import date

import pytest

from scripts.source_registry import (
    SourcePolicyError,
    load_registry,
    quarantine_paths,
    require_operation,
    review_status,
    validate_registry,
)


def test_every_registered_source_has_complete_review():
    assert validate_registry() == []
    assert {
        "dhi-crusaders", "fmg-medlands", "pase", "monasterium", "syriaca",
        "wikidata", "factgrid", "gnd", "pleiades",
    } <= load_registry().keys()


@pytest.mark.parametrize("source_id", ["dhi-crusaders", "fmg-medlands", "monasterium"])
def test_permission_required_sources_cannot_publish(source_id):
    with pytest.raises(SourcePolicyError, match="blocked"):
        require_operation(source_id, "public-export")


@pytest.mark.parametrize("source_id", ["syriaca", "wikidata", "factgrid", "gnd", "pleiades"])
def test_reviewed_open_sources_can_publish(source_id):
    assert require_operation(source_id, "public-export")["id"] == source_id


def test_unknown_adapter_source_fails_closed():
    with pytest.raises(SourcePolicyError, match="unregistered"):
        require_operation("invented-source", "canonical-export")


def test_quarantine_excludes_legacy_samples():
    paths = quarantine_paths()
    assert "data/dhi/dhi_sample_output.json" in paths
    assert "site/data/fmg_medlands_crusaders.json" in paths


def test_review_only_reports_staleness_and_never_changes_decision(tmp_path):
    registry = {
        "review_policy": {"stale_after_days": 30},
        "sources": [{"id": "x", "checked_at": "2026-01-01", "decision": "open-integrable"}],
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    before = path.read_bytes()
    report = review_status(path, today=date(2026, 7, 26))
    assert report["stale"] == [{"id": "x", "age_days": 206}]
    assert path.read_bytes() == before
