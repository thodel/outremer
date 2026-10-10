"""M19.4 part 1 (#94): QID backfill decides asserted / hypothesised / none."""

import json
import os
import sqlite3
from pathlib import Path

import pytest
from backfill_authority_qids import Checker, backfill
from wikidata_snapshot import Snapshot

SCHEMA = """
CREATE TABLE persons (qid TEXT PRIMARY KEY, label TEXT, description TEXT,
                      birth_year INTEGER, death_year INTEGER NOT NULL, hydrated_at TEXT);
CREATE TABLE names (qid TEXT, name TEXT, lang TEXT, kind TEXT);
CREATE VIRTUAL TABLE names_fts USING fts5(name, qid UNINDEXED,
                                          tokenize='unicode61 remove_diacritics 2');
CREATE TABLE snapshot (key TEXT PRIMARY KEY, value TEXT);
"""

PERSONS = [
    ("Q76721", "Godfrey of Bouillon", "Medieval Frankish knight", 1060, 1100),
    ("Q333306", "Robert II", "Count of Flanders (1065-1111)", 1065, 1111),
    ("Q1241350", "Robert II, Count of Dreux", "French noble", 1154, 1218),
    ("Q804832", "Baldwin of Ibelin", "noble", 1133, 1187),
    ("Q2891991", "Baldwin of Ibelin", "French nobleman", None, 1313),
    ("Q5564181", "Giraud II of Montreuil-Berlay", "French noble", None, 1155),
    ("Q5801647", "Fernando Pérez", "Castilian noble", None, 1289),
    ("Q76066403", "William IV Gouet", "French noble", None, 1170),
    ("Q1", "Godfrey of Bouillon", "a 15th-century namesake", 1400, 1470),
]
NAMES = [
    ("Q76721", "Godfrey of Bouillon", "en", "label"),
    ("Q76721", "Godefroy de Bouillon", "fr", "label"),
    ("Q333306", "Robert II", "en", "label"),
    ("Q333306", "Robert II de Flandre", "fr", "alias"),
    ("Q333306", "Roberto II de Flandes", "es", "label"),
    ("Q1241350", "Robert II, Count of Dreux", "en", "label"),
    ("Q804832", "Baldwin of Ibelin", "en", "label"),
    ("Q2891991", "Baldwin of Ibelin", "en", "label"),
    ("Q5564181", "Giraud II of Montreuil-Berlay", "en", "label"),
    ("Q5801647", "Fernando Pérez", "es", "label"),
    ("Q76066403", "William IV Gouet", "en", "label"),
    ("Q1", "Godfrey of Bouillon", "en", "label"),
]


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "snap.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO persons VALUES(?,?,?,?,?,'2026-10-02')", PERSONS)
    con.executemany("INSERT INTO names VALUES(?,?,?,?)", NAMES)
    con.executemany("INSERT INTO names_fts(name, qid) VALUES(?,?)", [(n, q) for q, n, _, _ in NAMES])
    con.execute("INSERT INTO snapshot VALUES('built_at','2026-10-02T21:00:00+00:00')")
    con.commit()
    con.close()
    return Snapshot(path)


def rec(aid, label, **name):
    return {"authority_id": aid, "preferred_label": label, "name": {"raw": label, **name},
            "variants": [label], "identifiers": {"project_identifier": aid[5:]}}


def test_exact_unique_match_in_period_is_asserted(snapshot):
    d = Checker(snapshot).decide(rec("AUTH:CR184", "Godfrey of Bouillon", name="Godfrey",
                                     toponym="Bouillon", pattern="of"))
    # the 15th-century namesake is outside the period and does not count
    assert d["verdict"] == "asserted" and d["qid"] == "Q76721"


def test_numeral_and_toponym_pin_a_person_the_string_score_cannot(snapshot):
    """Robert II: label 'Robert II', toponym only in description and aliases."""
    d = Checker(snapshot).decide(rec("AUTH:CR185", "Robert II of Flanders", name="Robert",
                                     regnal="II", toponym="Flanders", pattern="regnal_of"))
    assert d["verdict"] == "asserted" and d["qid"] == "Q333306"
    assert d["why"].startswith("numeral and toponym")


def test_label_equal_tie_is_hypothesised_never_asserted(snapshot):
    d = Checker(snapshot).decide(rec("AUTH:CRX", "Baldwin of Ibelin", name="Baldwin",
                                     toponym="Ibelin", pattern="of"))
    assert d["verdict"] == "hypothesised" and d["qid"] is None
    assert {c["qid"] for c in d["candidates"] if c["consistent"]} == {"Q804832", "Q2891991"}


def test_given_name_hidden_in_a_toponym_does_not_count(snapshot):
    """'Berlay II of Montreuil' vs 'Giraud II of Montreuil-Berlay': another man."""
    d = Checker(snapshot).decide(rec("AUTH:CR4", "Berlay II of Montreuil", name="Berlay",
                                     regnal="II", toponym="Montreuil", pattern="regnal_of"))
    assert d["verdict"] == "none"


def test_bare_two_token_name_is_at_most_hypothesised(snapshot):
    d = Checker(snapshot).decide(rec("AUTH:CR85", "Fernando Pérez", given="Fernando",
                                     rest="Pérez", pattern="space"))
    assert d["verdict"] == "hypothesised"


def test_a_numeral_the_record_lacks_is_a_hypothesis(snapshot):
    d = Checker(snapshot).decide(rec("AUTH:CR178", "William Gouet", given="William",
                                     rest="Gouet", pattern="space"))
    assert d["verdict"] == "hypothesised"
    assert "numeral" in d["why"] or "bare name" in d["why"]


def test_backfill_writes_only_asserted_qids_and_keeps_existing(snapshot):
    index = {"persons": [
        rec("AUTH:CR184", "Godfrey of Bouillon", name="Godfrey", toponym="Bouillon", pattern="of"),
        rec("AUTH:CR185", "Robert II of Flanders", name="Robert", regnal="II", toponym="Flanders",
            pattern="regnal_of"),
        rec("AUTH:CRX", "Baldwin of Ibelin", name="Baldwin", toponym="Ibelin", pattern="of"),
        rec("AUTH:CR4", "Berlay II of Montreuil", name="Berlay", regnal="II", toponym="Montreuil",
            pattern="regnal_of"),
    ]}
    index["persons"][0]["identifiers"]["wikidata_qid"] = "Q76721"
    out, audit = backfill(index, snapshot)
    ids = {p["authority_id"]: p["identifiers"] for p in out["persons"]}
    assert ids["AUTH:CR184"]["wikidata_qid"] == "Q76721" and "wikidata_qid_provenance" not in ids["AUTH:CR184"]
    assert ids["AUTH:CR185"]["wikidata_qid"] == "Q333306"
    assert ids["AUTH:CR185"]["wikidata_qid_provenance"]["status"] == "asserted"
    assert ids["AUTH:CR185"]["wikidata_qid_provenance"]["snapshot"] == "2026-10-02T21:00:00+00:00"
    assert "wikidata_qid" not in ids["AUTH:CRX"]
    assert [c["qid"] for c in ids["AUTH:CRX"]["wikidata_candidates"]] == ["Q804832", "Q2891991"]
    assert "wikidata_qid" not in ids["AUTH:CR4"] and "wikidata_candidates" not in ids["AUTH:CR4"]
    assert audit["counts"] == {"asserted": 2, "hypothesised": 1, "none": 1,
                               "kept_existing": 1, "existing_not_reproduced": 0}
    assert len(audit["records"]) == 4 and all("why" in r for r in audit["records"])


REAL = os.environ.get("WIKIDATA_SNAPSHOT")


@pytest.mark.skipif(not REAL or not Path(REAL).exists(), reason="needs the real pre-1500 snapshot")
def test_the_three_hand_verified_qids_are_reproduced_from_the_real_snapshot():
    index = json.loads((Path(__file__).resolve().parents[1] / "scripts" / "outremer_index.json")
                       .read_text(encoding="utf-8"))
    checker = Checker(Snapshot(REAL))
    by_id = {p["authority_id"]: p for p in index["persons"]}
    for aid, qid in (("AUTH:CR184", "Q76721"), ("AUTH:CR185", "Q333306"), ("AUTH:CR186", "Q266447")):
        d = checker.decide(by_id[aid])
        assert (d["verdict"], d["qid"]) == ("asserted", qid), d
