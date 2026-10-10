"""M19.2 tranche A (#92): the benchmark figures become attributed records."""

import json
from pathlib import Path

from add_benchmark_figures import HAND, next_number, parse_name, present

REPO = Path(__file__).resolve().parents[1]


def test_parse_name_mirrors_the_omeka_patterns():
    assert parse_name("Fulcher of Chartres") == {"raw": "Fulcher of Chartres", "name": "Fulcher",
                                                 "toponym": "Chartres", "pattern": "of"}
    assert parse_name("Alexios I Komnenos")["pattern"] == "space"
    assert parse_name("Henry the Lion")["epithet"] == "Lion"
    assert parse_name("Ibn al-Athir") == {"raw": "Ibn al-Athir", "name": "Ibn al-Athir", "pattern": None}
    assert parse_name("Tancred, Prince of Galilee")["name"] == "Tancred"


def test_present_matches_label_or_variant_case_insensitively():
    index = {"persons": [{"authority_id": "AUTH:CR184", "preferred_label": "Godfrey of Bouillon",
                          "variants": ["Duke Godfrey"]}]}
    assert present(index, {"preferred_label": "godfrey of bouillon"}) == "AUTH:CR184"
    assert present(index, {"preferred_label": "X", "variants": ["Duke Godfrey"]}) == "AUTH:CR184"
    assert present(index, {"preferred_label": "Fulcher of Chartres"}) is None
    assert next_number(index) == 185


def test_tranche_a_records_are_attributed_and_identified():
    index = json.loads((REPO / "scripts" / "outremer_index.json").read_text(encoding="utf-8"))
    audit = json.loads((REPO / "data" / "audits" / "epic19-tranche-a.json").read_text(encoding="utf-8"))
    by_id = {p["authority_id"]: p for p in index["persons"]}
    assert audit["counts"]["added"] == 14
    for row in audit["added"]:
        rec = by_id[row["authority_id"]]
        assert rec["provenance"]["source_system"] == "manual" and "#92" in rec["provenance"]["note"]
        for form in [rec["preferred_label"], *rec["variants"]]:
            assert rec["variant_provenance"].get(form), (row["authority_id"], form)
        qid = rec["identifiers"].get("wikidata_qid")
        assert qid, row["authority_id"]
        assert rec["identifiers"]["wikidata_qid_provenance"]["status"] == "asserted"
    assert by_id["AUTH:CR200"]["identifiers"]["wikidata_qid"] == HAND["Tancred, Prince of Galilee"][0]
    assert by_id["AUTH:CR190"]["identifiers"]["wikidata_qid"] == "Q5630"
