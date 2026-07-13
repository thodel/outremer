"""Tests for evaluation/metrics.py — extraction P/R/F1 and linking agreement."""

from evaluation.metrics import (
    extraction_prf,
    linking_agreement,
    normalise_name,
)

# ── normalise_name ───────────────────────────────────────────────────────────

def test_normalise_strips_accents_case_whitespace():
    assert normalise_name("  Godefroy   de Bouillon ") == "godefroy de bouillon"
    assert normalise_name("Raymond de Saint-Gilles") == normalise_name(
        "raymond de saint-gilles"
    )
    assert normalise_name("Adhémar") == "adhemar"


# ── extraction_prf ───────────────────────────────────────────────────────────

def test_prf_exact_hand_computed():
    res = extraction_prf(
        predicted=["Godfrey of Bouillon", "Peter the Hermit", "Motives of"],
        gold=["Godfrey of Bouillon", "Peter the Hermit", "Baldwin of Boulogne"],
    )
    assert (res["tp"], res["fp"], res["fn"]) == (2, 1, 1)
    assert res["precision"] == round(2 / 3, 4)
    assert res["recall"] == round(2 / 3, 4)
    assert res["false_positives"] == ["Motives of"]
    assert res["missed_gold"] == ["Baldwin of Boulogne"]


def test_prf_fuzzy_variant_spelling_matches():
    # particle drop ("le") scores just above the 90 threshold — a realistic
    # medieval name variant that exact matching would miss
    res = extraction_prf(["Adhémar of le Puy"], ["Adhemar of Puy"])
    assert res["tp"] == 1 and res["fp"] == 0 and res["fn"] == 0


def test_prf_connective_variant_matches_since_particle_folding():
    # pre-M10.1 this was a documented miss ("de"→"of" scored ~85 < 90);
    # particle folding (mirroring scripts/linker.py) makes the forms equal
    res = extraction_prf(["Godefroy de Bouillon"], ["Godefroy of Bouillon"])
    assert res["tp"] == 1 and res["fp"] == 0 and res["fn"] == 0


def test_prf_duplicate_predictions_are_false_positives():
    res = extraction_prf(
        ["Peter the Hermit", "Peter the Hermit"], ["Peter the Hermit"]
    )
    assert (res["tp"], res["fp"], res["fn"]) == (1, 1, 0)


def test_prf_empty_inputs():
    assert extraction_prf([], [])["f1"] == 0.0
    assert extraction_prf(["X"], [])["fp"] == 1
    assert extraction_prf([], ["X"])["fn"] == 1


# ── linking_agreement ────────────────────────────────────────────────────────

LINKS = [
    {"person": "Miles of Clermont", "top_candidate": {"authority_id": "AUTH:CR115"}},
    {"person": "Peter the Hermit", "top_candidate": None},
]


def test_agreement_accept_hit_and_miss():
    res = linking_agreement(
        LINKS,
        accepted=[("Miles of Clermont", "AUTH:CR115"), ("Peter the Hermit", "AUTH:CR7")],
        rejected=[],
    )
    assert res["accept_hit"] == 1
    assert res["accept_miss"] == 1
    assert res["agreement"] == 0.5


def test_agreement_reject_hit_is_bad_avoided_is_good():
    res = linking_agreement(
        LINKS,
        accepted=[],
        rejected=[("Miles of Clermont", "AUTH:CR115"), ("Miles of Clermont", "AUTH:CR119")],
    )
    # pipeline still proposes CR115 (reject_hit); it does not propose CR119
    assert res["reject_hit"] == 1
    assert res["reject_avoided"] == 1
    assert res["agreement"] == 0.5


def test_agreement_whitespace_artifacts_in_person_names():
    # decisions.json contains names like "Miles of \n Clermont"
    res = linking_agreement(
        LINKS, accepted=[("Miles of  \n Clermont", "AUTH:CR115")], rejected=[]
    )
    assert res["accept_hit"] == 1


def test_agreement_no_reviewed_pairs():
    assert linking_agreement(LINKS, [], [])["agreement"] == 0.0


# ── split_pairs_by_system / wikidata_agreement ───────────────────────────────

from evaluation.metrics import split_pairs_by_system, wikidata_agreement


def test_split_pairs_by_id_namespace():
    auth, wd = split_pairs_by_system(
        [("A", "AUTH:CR1"), ("B", "wikidata:Q42"), ("C", "AUTH:CR2")]
    )
    assert auth == [("A", "AUTH:CR1"), ("C", "AUTH:CR2")]
    assert wd == [("B", "wikidata:Q42")]


WD_ENTRIES = {
    "godfrey of bouillon": {
        "candidates": [
            {"qid": "Q999", "score": 0.4},
            {"qid": "Q76721", "score": 0.9},
        ]
    },
    "no candidates person": {"candidates": []},
}


def test_wikidata_agreement_top_scored_candidate_wins():
    res = wikidata_agreement(
        WD_ENTRIES,
        accepted=[("Godfrey of Bouillon", "wikidata:Q76721")],
        rejected=[("Godfrey of Bouillon", "wikidata:Q999")],
    )
    assert res["accept_hit"] == 1
    assert res["reject_avoided"] == 1  # Q999 is not the top proposal
    assert res["agreement"] == 1.0


def test_wikidata_agreement_missing_mention_is_a_miss():
    res = wikidata_agreement(
        WD_ENTRIES, accepted=[("Unknown Person", "wikidata:Q1")], rejected=[]
    )
    assert res["accept_miss"] == 1
