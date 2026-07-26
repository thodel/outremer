import json
import shutil
from pathlib import Path

import pytest

from scripts.integrations.syriaca_tei import (
    DisabledLiveApiAdapter,
    SyriacaTeiAdapter,
    verify_checkout,
)

COMMIT = "fefe80f5aabebeef5ee3cef66d3d344cf573f173"
FIXTURES = Path(__file__).parent / "fixtures" / "syriaca"


def adapter():
    return SyriacaTeiAdapter(commit=COMMIT)


def test_requires_full_pinned_commit():
    with pytest.raises(ValueError, match="40-character"):
        SyriacaTeiAdapter(commit="master")


def test_person_mapping_preserves_multilingual_provenance_and_rights():
    record = adapter().parse_file(
        FIXTURES / "person.xml", relative_path="data/persons/tei/123.xml"
    )
    assert record["uri"] == "http://syriaca.org/person/123"
    assert {name["language"] for name in record["names"]} == {"en", "syr"}
    assert record["names"][0]["xml_id"]
    assert "#bib123-1" in record["source_pointers"]
    assert record["bibliography"][0]["xml_id"] == "bib123-1"
    assert record["revision"][0]["when"] == "2023-10"
    assert record["licence"]["target"].endswith("/by/3.0/")
    assert record["licence"]["third_party_material"] is True
    assert record["snapshot"]["commit"] == COMMIT
    assert len(record["snapshot"]["checksum"]) == 64


def test_spear_factoid_remains_source_assertion_with_locator():
    record = adapter().parse_file(
        FIXTURES / "spear.xml", relative_path="data/spear/tei/999.xml"
    )
    assert record["record_type"] == "spear"
    assert record["events"][0]["source"] == "#bib999-1"
    assert record["relations"][0]["source"] == "#bib999-1"
    assert "not collapsed into canonical truth" in record["editorial_status"]


def test_selection_is_temporal_and_geographic():
    record = adapter().parse_file(
        FIXTURES / "person.xml", relative_path="data/persons/tei/123.xml"
    )
    assert adapter().relevant_to_pilot(record)
    record["events"][0]["text"] = "Visited Iceland"
    record["events"][0]["places"] = []
    record["uri"] = "http://example.test/no-region"
    assert not adapter().relevant_to_pilot(record)


def test_snapshot_round_trip_is_deterministic(tmp_path):
    records = [
        adapter().parse_file(FIXTURES / name, relative_path=f"data/{name}")
        for name in ("person.xml", "spear.xml")
    ]
    path = adapter().write_snapshot(records, tmp_path / "snapshot.json")
    first = path.read_bytes()
    loaded = json.loads(first)
    adapter().write_snapshot(list(reversed(records)), path)
    assert path.read_bytes() == first
    assert loaded["commit"] == COMMIT
    assert len(loaded["records"]) == 2


def test_attribution_distinguishes_third_party_material():
    record = adapter().parse_file(
        FIXTURES / "person.xml", relative_path="data/persons/tei/123.xml"
    )
    attribution = adapter().attribution(record)
    assert attribution["record_uri"] == record["uri"]
    assert attribution["commit"] == COMMIT
    assert attribution["third_party_material_requires_review"] is True


def test_wrong_checkout_commit_is_rejected(tmp_path, monkeypatch):
    class Result:
        stdout = "0" * 40 + "\n"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())
    with pytest.raises(ValueError, match="expected pinned"):
        verify_checkout(tmp_path, COMMIT)


def test_checkout_loader_verifies_commit_and_selects_pilot(tmp_path, monkeypatch):
    target = tmp_path / "data" / "persons" / "tei"
    target.mkdir(parents=True)
    shutil.copy(FIXTURES / "person.xml", target / "123.xml")

    class Result:
        stdout = COMMIT + "\n"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())
    records = adapter().load_checkout(tmp_path, ("data/persons/tei",))
    assert [record["uri"] for record in records] == ["http://syriaca.org/person/123"]


def test_live_api_cannot_silently_replace_snapshot():
    with pytest.raises(RuntimeError, match="disabled"):
        DisabledLiveApiAdapter().fetch("person/123")
