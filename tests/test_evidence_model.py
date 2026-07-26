import json
from pathlib import Path

import pytest

from scripts.evidence_model import (
    EvidenceContractError,
    canonical_bytes,
    import_snapshot,
    stable_id,
    validate_dataset,
)
from scripts.migrate_evidence_model import dry_run

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "evidence-first" / "representative.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_representative_fixture_covers_contract_and_is_valid():
    data = fixture()
    assert validate_dataset(data) == []
    types = {obj["type"] for obj in data["objects"]}
    assert {
        "source_work", "manifestation", "snapshot", "passage", "mention",
        "assertion", "person", "group", "identity_hypothesis", "decision",
    } <= types


def test_every_assertion_has_precise_snapshot_backed_evidence():
    data = fixture()
    index = {obj["id"]: obj for obj in data["objects"]}
    for assertion in (obj for obj in data["objects"] if obj["type"] == "assertion"):
        for passage_id in assertion["passage_ids"]:
            passage = index[passage_id]
            assert passage["locator"]
            assert index[passage["snapshot_id"]]["type"] == "snapshot"


def test_mentions_keep_verbatim_language_and_script():
    mention = next(obj for obj in fixture()["objects"] if obj["id"].endswith(":baldwin"))
    assert mention["verbatim"] == "Baldwin"
    assert mention["language"] == "en"
    assert mention["script"] == "Latn"


def test_rejected_and_superseded_decisions_preserve_history():
    data = fixture()
    statuses = [obj["status"] for obj in data["objects"] if obj["type"] == "decision"]
    assert {"accepted", "rejected", "superseded"} <= set(statuses)
    assert any(obj.get("supersedes") for obj in data["objects"])


def test_importing_same_snapshot_twice_is_byte_idempotent():
    empty = {"schema_version": "1.0.0", "objects": []}
    snapshot = {
        "id": stable_id("snapshot", "source", "sha"),
        "type": "snapshot", "version": 1,
        "manifestation_id": stable_id("manifestation", "source"),
        "checksum": "a" * 64, "retrieved_at": "2026-07-26T00:00:00Z",
        "source_locator": "source.json",
    }
    manifestation = {
        "id": snapshot["manifestation_id"], "type": "manifestation", "version": 1,
        "work_id": stable_id("source_work", "work"), "citation": "Fixture",
    }
    work = {
        "id": manifestation["work_id"], "type": "source_work", "version": 1,
        "title": "Fixture work",
    }
    once = import_snapshot(empty, snapshot, [work, manifestation])
    twice = import_snapshot(once, snapshot, [work, manifestation])
    assert canonical_bytes(once) == canonical_bytes(twice)


def test_snapshot_id_cannot_be_reused_for_other_content():
    data = fixture()
    snapshot = next(obj for obj in data["objects"] if obj["type"] == "snapshot")
    changed = {**snapshot, "checksum": "f" * 64}
    with pytest.raises(EvidenceContractError, match="different checksum"):
        import_snapshot(data, changed, [])


def test_migration_dry_run_maps_all_current_structures_without_writing_decisions():
    report = dry_run(ROOT)
    assert set(report["mappings"]) == {
        "authority", "wikidata", "extractions", "dhi_quarantine", "fmg_quarantine",
    }
    assert report["decisions_unchanged"] is True
    assert report["decisions_sha256_before"] == report["decisions_sha256_after"]
