"""Closest-reading evaluation tests for selection-derived recognition data."""

import pytest

from evaluation.metrics import selection_metrics, validate_selection_event


def test_selection_metrics_report_coverage_agreement_and_regret():
    events = [
        {
            "candidates": ["deus vult", "deus uult"],
            "automatic_selection": "deus vult",
            "human_selection": "deus vult",
        },
        {
            "candidates": ["rex francorum", "rex francerum"],
            "automatic_selection": "rex francerum",
            "human_selection": "rex francorum",
        },
        {
            "candidates": ["unusable", "also unusable"],
            "automatic_selection": "unusable",
            "human_selection": None,
        },
    ]

    result = selection_metrics(events)
    assert result["events"] == 3
    assert result["covered"] == 2
    assert result["coverage"] == 2 / 3
    assert result["comparable_selections"] == 2
    assert result["automatic_matches"] == 1
    assert result["selection_agreement"] == 0.5
    assert result["mean_regret_cer"] == pytest.approx(1 / 26)


def test_no_automatic_choice_is_excluded_from_selection_comparison():
    result = selection_metrics(
        [
            {
                "candidates": ["acceptable"],
                "automatic_selection": None,
                "human_selection": "acceptable",
            }
        ]
    )
    assert result["coverage"] == 1.0
    assert result["comparable_selections"] == 0
    assert result["selection_agreement"] == 0.0


@pytest.mark.parametrize("field", ["ground_truth", "gold", "GROUND_TRUTH"])
def test_selection_payload_rejects_truth_claim_field_names(field):
    with pytest.raises(ValueError, match="truth-claim"):
        validate_selection_event(
            {
                "candidates": ["a"],
                "automatic_selection": "a",
                "human_selection": "a",
                "metadata": {field: "a"},
            }
        )


def test_selection_must_refer_to_an_offered_candidate():
    with pytest.raises(ValueError, match="offered candidates"):
        validate_selection_event(
            {
                "candidates": ["offered"],
                "automatic_selection": "invented",
                "human_selection": "offered",
            }
        )
