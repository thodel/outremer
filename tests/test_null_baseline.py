"""Tests for the null-linker reference (evaluation/metrics.py).

The authority gold is reject-dominated (7 accepts / 48 rejects as of
2026-07-30), which means a linker that proposes *nothing* scores 48/55 =
0.873 while the real linker scored 0.891. Agreement alone therefore cannot
distinguish a working linker from a disabled one; these tests lock in the
diagnostics that make that visible.
"""

from evaluation.metrics import linking_agreement, null_reference, wikidata_agreement

# A linker that proposes nothing at all.
NULL_LINKS: list[dict] = []

LIVE_LINKS = [
    {"person": "Miles of Clermont", "top_candidate": {"outremer_id": "AUTH:CR115"}},
]


# ── null_reference arithmetic ────────────────────────────────────────────────

def test_null_reference_reject_dominated_gold():
    # 7 accepts / 48 rejects: doing nothing already scores 48/55
    res = null_reference(7, 48, agreement=0.8909, accept_hit=4)
    assert res["null_agreement"] == 0.8727
    assert res["lift_over_null"] == round(0.8909 - 0.8727, 4)
    assert res["negative_share"] == 0.8727
    assert res["accept_rate"] == round(4 / 7, 4)


def test_null_reference_accept_only_gold_has_zero_floor():
    # wikidata gold is all accepts: a do-nothing system scores 0
    res = null_reference(16, 0, agreement=1.0, accept_hit=16)
    assert res["null_agreement"] == 0.0
    assert res["lift_over_null"] == 1.0
    assert res["accept_rate"] == 1.0


def test_null_reference_empty_gold_is_not_a_crash():
    res = null_reference(0, 0, agreement=0.0, accept_hit=0)
    assert res["null_agreement"] == 0.0
    assert res["accept_rate"] == 0.0


# ── the property that matters ────────────────────────────────────────────────

def test_null_linker_scores_exactly_the_null_baseline():
    """A linker proposing nothing must score its own null baseline, lift 0."""
    accepted = [(f"Person {i}", f"AUTH:CR{i}") for i in range(7)]
    rejected = [(f"Other {i}", f"AUTH:CR{100 + i}") for i in range(48)]

    res = linking_agreement(NULL_LINKS, accepted, rejected)

    assert res["accept_hit"] == 0
    assert res["reject_avoided"] == 48
    assert res["agreement"] == res["null_agreement"]
    assert res["lift_over_null"] == 0.0
    assert res["accept_rate"] == 0.0


def test_reject_dominated_gold_flatters_a_useless_linker():
    """Guard the headline finding: 0.87 agreement with zero positive signal."""
    accepted = [(f"Person {i}", f"AUTH:CR{i}") for i in range(7)]
    rejected = [(f"Other {i}", f"AUTH:CR{100 + i}") for i in range(48)]

    res = linking_agreement(NULL_LINKS, accepted, rejected)

    # Looks respectable...
    assert res["agreement"] > 0.87
    # ...but carries no evidence the linker works.
    assert res["lift_over_null"] == 0.0
    assert res["accept_rate"] == 0.0


def test_lift_rewards_a_linker_that_finds_accepts():
    accepted = [("Miles of Clermont", "AUTH:CR115")]
    rejected = [("Other", "AUTH:CR999")]

    res = linking_agreement(LIVE_LINKS, accepted, rejected)

    assert res["accept_hit"] == 1
    assert res["accept_rate"] == 1.0
    assert res["lift_over_null"] > 0


# ── the same guarantee for the wikidata segment ──────────────────────────────

def test_wikidata_agreement_carries_null_reference():
    entries = {
        "godfrey of bouillon": {"candidates": [{"qid": "Q76721", "score": 0.9}]},
    }
    res = wikidata_agreement(
        entries, accepted=[("Godfrey of Bouillon", "wikidata:Q76721")], rejected=[]
    )
    assert res["accept_hit"] == 1
    # accept-only gold → a do-nothing system would score 0
    assert res["null_agreement"] == 0.0
    assert res["lift_over_null"] == 1.0
