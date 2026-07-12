"""Matcher-level tests for scripts/linker.py (M10.1 + M10.2).

Each case documents a measured weakness of the pre-Epic-10 matcher or a
failure mode the ensemble must not reintroduce. Scores are asserted as
inequalities against the config thresholds, not exact values, so rapidfuzz
version bumps don't break the suite.
"""

from config import LINK_CANDIDATE_FLOOR, LINK_HIGH
from linker import _fuzzy_score, fold_particles, link_voyagers_to_outremer, normalise

from evaluation import metrics as eval_metrics

# ── normalise / fold_particles ───────────────────────────────────────────────

def test_hyphenated_toponym_splits():
    assert normalise("Raymond of Saint-Gilles") == "raymond of saint gilles"


def test_fold_drops_connective_particles():
    assert fold_particles("godefroy de bouillon") == "godefroy bouillon"
    assert fold_particles("godefroy of bouillon") == "godefroy bouillon"


def test_fold_keeps_arabic_name_structure():
    # ibn/al are name-bearing, not connective — must survive folding
    assert fold_particles("hunayn ibn ishaq") == "hunayn ibn ishaq"


def test_fold_never_reduces_below_two_tokens():
    assert fold_particles("de godefroy") == "de godefroy"


def test_eval_metrics_particle_set_matches_linker():
    # evaluation/metrics.py mirrors the linker's particle handling; keep
    # the two in lockstep or eval and production disagree on equivalence
    from linker import _PARTICLES as linker_particles

    assert eval_metrics._PARTICLES == linker_particles
    for name in ["godefroy de bouillon", "raymond of saint gilles", "hunayn ibn ishaq"]:
        assert eval_metrics._fold_particles(name) == fold_particles(name)


# ── ensemble scoring (M10.2) ────────────────────────────────────────────────

def test_connective_variants_now_match_high():
    # pre-Epic-10: token_sort("godefroy de bouillon","godefroy of bouillon")
    # = 0.85 < high bar. Particle folding makes them identical.
    assert _fuzzy_score("godefroy de bouillon", "godefroy of bouillon") >= LINK_HIGH


def test_hyphen_plus_connective_variant_matches():
    a = normalise("Raymond de Saint-Gilles")
    b = normalise("Raymond of Saint Gilles")
    assert _fuzzy_score(a, b) >= LINK_HIGH


def test_shared_first_name_and_particle_stay_distinct():
    # measured failure of a naive token_set ensemble: "Ralph of Caen" vs
    # "Ralph II of Fougères" reached 0.79 via the shared "ralph"+"of".
    # Different persons must stay below the candidate floor + margin.
    assert _fuzzy_score("ralph of caen", "ralph ii of fougeres") < 0.70
    assert _fuzzy_score("count robert of flanders", "thierry of flanders") < 0.75


# ── end-to-end linking ──────────────────────────────────────────────────────

AUTHORITY = [
    {
        "authority_id": "AUTH:T1",
        "preferred_label": "Godefroy of Bouillon",
        "type": "person",
        "all_norms": ["godefroy of bouillon", "godefroy bouillon"],
    },
    {
        "authority_id": "AUTH:T2",
        "preferred_label": "Ralph II of Fougères",
        "type": "person",
        "all_norms": ["ralph ii of fougeres", "ralph"],
    },
]


def test_link_connective_variant_is_high_confidence():
    links = link_voyagers_to_outremer([{"name": "Godefroy de Bouillon"}], AUTHORITY)
    top = links[0]["top_candidate"]
    assert top and top["outremer_id"] == "AUTH:T1"
    assert links[0]["status"] == "high"


def test_link_does_not_borrow_single_token_variant():
    # the authority file contains bare given-name variants ("Ralph");
    # they must not pull unrelated multi-token mentions above the floor
    links = link_voyagers_to_outremer([{"name": "Ralph of Caen"}], AUTHORITY)
    top = links[0]["top_candidate"]
    assert top is None or top["score"] < LINK_HIGH


def test_floor_is_config_backed():
    assert 0.0 < LINK_CANDIDATE_FLOOR < LINK_HIGH <= 1.0
