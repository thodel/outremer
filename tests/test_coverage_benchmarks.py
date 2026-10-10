"""M19.2 tranche B (#92): coverage counted against sourced lists, QID first."""

import json
from pathlib import Path

from audit_authority_coverage import audit_list, audit_many
from fetch_wikidata_benchmarks import CRUSADES, OFFICES, crusade_query, latin_east_query, to_figures

REPO = Path(__file__).resolve().parents[1]

AUTHORITY = {"persons": [
    {"authority_id": "AUTH:CR184", "preferred_label": "Godfrey of Bouillon", "variants": ["Godfrey"],
     "identifiers": {"wikidata_qid": "Q76721"}},
    {"authority_id": "AUTH:CR75", "preferred_label": "Hugh de Beauchamp", "variants": [],
     "identifiers": {"wikidata_candidates": [{"qid": "Q16197364"}, {"qid": "Q18730449"}]}},
    {"authority_id": "AUTH:CR197", "preferred_label": "Ibn al-Athir", "variants": [], "identifiers": {}},
    {"authority_id": "AUTH:CR56", "preferred_label": "Robert of Milly", "variants": ["Robert"], "identifiers": {}},
]}


def test_qid_first_then_candidates_then_whole_names_never_single_words():
    benchmark = {"id": "t", "figures": [
        {"preferred_label": "Godefroy de Bouillon", "wikidata": "Q76721"},          # by QID, label differs
        {"preferred_label": "Hugh de Beauchamp", "wikidata": "Q18730449"},          # hypothesised
        {"preferred_label": "Ibn al-Athir", "wikidata": "Q334854"},                 # by name (multi-word)
        {"preferred_label": "Robert", "wikidata": "Q999"},                          # single word: never by name
        {"preferred_label": "Peter the Hermit", "wikidata": "Q1000"},               # missing
    ]}
    report = audit_list(AUTHORITY, benchmark)
    status = {row["preferred_label"]: (row["status"], row["authority_id"]) for row in report["figures"]}
    assert status["Godefroy de Bouillon"] == ("present", "AUTH:CR184")
    assert status["Hugh de Beauchamp"] == ("hypothesised", "AUTH:CR75")
    assert status["Ibn al-Athir"] == ("present_by_name", "AUTH:CR197")
    assert status["Robert"] == ("missing", None)
    assert status["Peter the Hermit"] == ("missing", None)
    assert report["summary"] == {"hypothesised": 1, "missing": 2, "present": 1, "present_by_name": 1}


def test_audit_many_reports_each_list(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps(AUTHORITY))
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"id": "list-a", "source": "wikidata", "figures": [{"preferred_label": "x", "wikidata": "Q76721"}]}))
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"id": "list-b", "source": "manual", "figures": [{"preferred_label": "Nobody Here"}]}))
    report = audit_many(auth, [a, b])
    assert report["authority_records"] == 4
    assert [(item["id"], item["summary"]) for item in report["lists"]] == [
        ("list-a", {"present": 1}), ("list-b", {"missing": 1})]


def test_sparql_rows_become_figures_sorted_by_death_year():
    rows = [
        {"p": {"value": "http://www.wikidata.org/entity/Q2"}, "pLabel": {"value": "Later Man"},
         "death": {"value": "1150-01-01T00:00:00Z"}, "desc": {"value": "knight"}},
        {"p": {"value": "http://www.wikidata.org/entity/Q1"}, "pLabel": {"value": "Earlier Man"},
         "death": {"value": "1099-07-15T00:00:00Z"}, "birth": {"value": "1060-01-01T00:00:00Z"}},
        {"p": {"value": "http://www.wikidata.org/entity/Q1"}, "pLabel": {"value": "Earlier Man"},
         "death": {"value": "1099-07-15T00:00:00Z"}},  # duplicate row from a second UNION branch
    ]
    figures = to_figures(rows)
    assert [f["wikidata"] for f in figures] == ["Q1", "Q2"]
    assert figures[0] == {"preferred_label": "Earlier Man", "wikidata": "Q1", "birth_year": 1060,
                          "death_year": 1099, "description": ""}
    assert figures[1]["description"] == "knight"


def test_queries_name_the_crusades_and_the_offices():
    assert CRUSADES["first-crusade"] == "Q51649"
    assert "wd:Q51649" in crusade_query("Q51649") and "P607" in crusade_query("Q51649")
    q = latin_east_query()
    assert '"King of Jerusalem"@en' in q and "P39" in q and "1095" in q and "1131" in q
    assert "Prince of Antioch" in OFFICES


def test_committed_benchmark_lists_are_rights_clean_and_sourced():
    for path in (REPO / "data" / "audits" / "benchmarks").glob("wikidata-*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["source"] == "wikidata" and data["licence"] == "CC0 1.0", path.name
        assert data["query"] and data["fetched_at"] and data["status"] == "ok", path.name
        assert all(f.get("wikidata", "").startswith("Q") for f in data["figures"]), path.name


def test_the_printed_reference_works_are_registered_reference_only():
    registry = json.loads((REPO / "data" / "sources" / "registry.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in registry["sources"]}
    for sid in ("riley-smith-first-crusaders-1997", "murray-crusader-kingdom-2000"):
        assert by_id[sid]["decision"] == "reference-only"
        assert by_id[sid]["permitted_operations"] == ["reference"]
        assert by_id[sid]["snapshot"] is None
