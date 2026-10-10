"""M19.1 (#91): variants from the snapshot, with provenance, never bare."""

import sqlite3

import pytest
from enrich_authority_variants import clean_form, enrich, enrich_record, is_bare, is_title
from wikidata_snapshot import Snapshot

SCHEMA = """
CREATE TABLE persons (qid TEXT PRIMARY KEY, label TEXT, description TEXT,
                      birth_year INTEGER, death_year INTEGER NOT NULL, hydrated_at TEXT);
CREATE TABLE names (qid TEXT, name TEXT, lang TEXT, kind TEXT);
CREATE VIRTUAL TABLE names_fts USING fts5(name, qid UNINDEXED,
                                          tokenize='unicode61 remove_diacritics 2');
CREATE TABLE snapshot (key TEXT PRIMARY KEY, value TEXT);
"""
NAMES = [
    ("Q266447", "Ralph of Caen", "en", "label"),
    ("Q266447", "Radulph of Caen", "en", "alias"),
    ("Q266447", "Radulfus Cadomensis", "la", "label"),
    ("Q266447", "Raoul de Caen", "fr", "label"),
    ("Q266447", "Radulf", "fr", "alias"),
    ("Q105378", "Henry the Lion", "en", "label"),
    ("Q105378", "Henry III", "en", "alias"),
    ("Q105378", "Heinrich der Löwe", "de", "label"),
    ("Q105378", "Heinrich III. (Sachsen)", "de", "alias"),
    ("Q105378", "هنري الأسد", "ar", "alias"),
]


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "snap.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO persons VALUES(?,?,?,?,?,'x')",
                    [("Q266447", "Ralph of Caen", "", None, 1120), ("Q105378", "Henry the Lion", "", 1129, 1195)])
    con.executemany("INSERT INTO names VALUES(?,?,?,?)", NAMES)
    con.executemany("INSERT INTO names_fts(name, qid) VALUES(?,?)", [(n, q) for q, n, _, _ in NAMES])
    con.execute("INSERT INTO snapshot VALUES('built_at','2026-10-02T21:00:00+00:00')")
    con.commit()
    con.close()
    return Snapshot(path)


def ralph():
    return {"authority_id": "AUTH:CR186", "preferred_label": "Ralph of Caen",
            "variants": ["Radulph of Caen", "Ralph", "Ralph (Caen)"],
            "normalized": {"preferred": "ralph of caen", "variants": ["radulph of caen", "ralph", "ralph caen"]},
            "identifiers": {"project_identifier": "CR186", "wikidata_qid": "Q266447"},
            "variant_provenance": {"Ralph of Caen": [{"system": "github-issue", "locator": "issue:45"}]}}


@pytest.mark.parametrize("form,bare", [
    ("Robert II", True), ("Heinrich III.", True), ("Fulko", True), ("Radulf", True),
    ("Roberto II di Fiandra", False), ("Heinrich der Löwe", False), ("Radulfus Cadomensis", False),
    ("Fulko von Jerusalem", False), ("Saint Louis", True), ("Henry III", True),
])
def test_bare_forms_are_recognised(form, bare):
    assert is_bare(form) is bare


def test_snapshot_forms_are_added_with_provenance_and_normalised(snapshot):
    rec = ralph()
    report = enrich_record(rec, snapshot)
    added = {a["form"] for a in report["added"]}
    assert added == {"Radulfus Cadomensis", "Raoul de Caen"}
    assert report["skipped_bare"] == ["Radulf"]
    assert report["skipped_known"] == 2          # Ralph of Caen, Radulph of Caen
    assert rec["variant_provenance"]["Radulfus Cadomensis"] == [{
        "system": "wikidata-pre1500-snapshot", "locator": "Q266447", "lang": "la",
        "kind": "label", "snapshot": "2026-10-02T21:00:00+00:00"}]
    assert "radulfus cadomensis" in rec["normalized"]["variants"]
    assert "raoul de caen" in rec["normalized"]["variants"]
    # nothing existing was touched
    assert rec["variant_provenance"]["Ralph of Caen"] == [{"system": "github-issue", "locator": "issue:45"}]
    assert {"Radulph of Caen", "Ralph", "Ralph (Caen)"} <= set(rec["variants"])


def test_a_record_without_qid_is_left_alone(snapshot):
    rec = ralph()
    del rec["identifiers"]["wikidata_qid"]
    before = {k: (list(v) if isinstance(v, list) else v) for k, v in rec.items()}
    report = enrich_record(rec, snapshot)
    assert report.get("skipped") == "no QID" and report["added"] == []
    assert rec["variants"] == before["variants"]


def test_bare_numeral_forms_of_a_namesake_king_stay_out(snapshot):
    """Henry the Lion is also 'Henry III' of Saxony: that form must not join,
    or every Henry III in the corpus would link to him."""
    rec = {"authority_id": "AUTH:CR26", "preferred_label": "Henry the Lion", "variants": ["Henry"],
           "normalized": {"preferred": "henry the lion", "variants": ["henry"]},
           "identifiers": {"wikidata_qid": "Q105378"}}
    report = enrich_record(rec, snapshot)
    assert "Henry III" in report["skipped_bare"]
    assert "Heinrich III. (Sachsen)" in report["skipped_bare"]   # cleaned to "Heinrich III."
    assert {a["form"] for a in report["added"]} == {"Heinrich der Löwe", "هنري الأسد"}


def test_enrich_counts(snapshot):
    index = {"persons": [ralph(), {"authority_id": "AUTH:CR9", "preferred_label": "R. Gabard",
                                   "variants": [], "identifiers": {}}]}
    _, audit = enrich(index, snapshot)
    assert audit["counts"]["records_with_qid"] == 1
    assert audit["counts"]["forms_added"] == 2 and audit["counts"]["by_lang"] == {"la": 1, "fr": 1}
    assert [r["authority_id"] for r in audit["records"]] == ["AUTH:CR186"]


@pytest.mark.parametrize("form,expected", [
    ("Stephen de Sancerre, Count of Sancerre", "Stephen de Sancerre"),
    ("Gerard van Loon (graaf)", "Gerard van Loon"),
    ("Heinrich III. (Sachsen)", "Heinrich III."),
    ("Radulfus Cadomensis", "Radulfus Cadomensis"),
])
def test_clean_form_keeps_the_name_part(form, expected):
    assert clean_form(form) == expected


@pytest.mark.parametrize("form,title", [
    ("Fulk, King of Jerusalem", True), ("King of Jerusalem", True), ("Conrad I, King of Jerusalem", True),
    ("Rognvald Kolsson, Jarl of Orkney", True), ("Gerard Graaf van Loon en Rieneck", True),
    ("Fulko von Jerusalem", True), ("Pierre de France", True), ("Constance de France", True),
    ("Roberto II di Fiandra", False), ("Radulfus Cadomensis", False), ("Heinrich der Löwe", False),
    ("Thierry d'Alsace", False), ("Rodrigo Álvarez de Sarria", False),
])
def test_titles_and_realms_are_not_names(form, title):
    assert is_title(form) is title


def test_the_measured_false_positives_of_the_first_run_cannot_recur():
    """2026-10-10: 'the people of Jerusalem' → Fulk V via 'Fulk, King of Jerusalem'
    and 'Franciscans of Jerusalem' → Conrad of Montferrat via
    'Conrad I, King of Jerusalem'. The cleaned form is bare and the raw one a title."""
    for raw in ("Fulk, King of Jerusalem", "Conrad I, King of Jerusalem", "فولك ملك بيت المقدس"):
        assert is_title(clean_form(raw)) or is_bare(clean_form(raw)), raw
