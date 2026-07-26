import json
from pathlib import Path

from scripts.integrations.open_authorities import (
    FactGridAdapter,
    GNDAdapter,
    PleiadesAdapter,
    WikidataAdapter,
    candidate_features,
)

FIXTURES = Path(__file__).parent / "fixtures" / "open_authorities"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_wikidata_keeps_revision_qualifiers_and_references():
    record = WikidataAdapter().map_record(load("wikidata")[0])
    assert record["revision"] == 12345
    statement = record["statements"][0]
    assert statement["qualifiers"]["P580"][0]["precision"] == 7
    assert statement["references"][0]["P248"] == ["Q123"]


def test_factgrid_remains_source_distinct():
    record = FactGridAdapter().map_record(load("factgrid")[0])
    assert record["source"] == "factgrid"
    assert record["source_uri"] == "https://database.factgrid.de/entity/Q900001"
    assert "wikidata.org" not in record["source_uri"]


def test_gnd_keeps_identifier_and_names():
    record = GNDAdapter().map_record(load("gnd")[0])
    assert record["source_uri"].endswith("/118654195")
    assert "Baldwin I of Jerusalem" in record["variant_names"]
    assert record["licence"] == "CC0-1.0"


def test_pleiades_keeps_temporal_geometry_and_warning():
    record = PleiadesAdapter().map_record(load("pleiades")[0])
    assert record["locations"][0]["geometry"]["type"] == "Point"
    assert record["locations"][0]["time_periods"] == ["roman"]
    assert "ancient-world" in record["medieval_scope_warning"]


def test_snapshot_is_deterministic_and_idempotent(tmp_path):
    adapter = WikidataAdapter()
    kwargs = {"retrieval_time": "2026-07-26T00:00:00Z", "source_version": "revid-set-1"}
    first = adapter.build_snapshot(load("wikidata"), **kwargs)
    second = adapter.build_snapshot(load("wikidata"), **kwargs)
    path = tmp_path / "snapshot.json"
    adapter.write_snapshot(first, path)
    bytes_once = path.read_bytes()
    adapter.write_snapshot(second, path)
    assert path.read_bytes() == bytes_once
    assert first.checksum == second.checksum


def test_downtime_fallback_does_not_touch_review_history(tmp_path):
    adapter = GNDAdapter()
    snapshot = adapter.build_snapshot(
        load("gnd"), retrieval_time="2026-07-26T00:00:00Z", source_version="sru-v1"
    )
    path = adapter.write_snapshot(snapshot, tmp_path / "gnd.json")
    before = path.read_bytes()
    loaded = adapter.load_last_verified(path)
    assert loaded.checksum == snapshot.checksum
    assert path.read_bytes() == before


def test_label_equality_never_asserts_identity():
    candidate = GNDAdapter().map_record(load("gnd")[0])
    features = candidate_features(
        {"preferred_name": "Baldwin I of Jerusalem", "variant_names": [], "dates": {}},
        candidate,
    )
    assert features["label_overlap"] == ["baldwin i of jerusalem"]
    assert features["identity_asserted"] is False
    assert features["requires_curator_review"] is True
