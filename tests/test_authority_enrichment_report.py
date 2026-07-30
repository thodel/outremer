from evaluation.authority_enrichment_report import build_report


def test_epic19_report_contains_comparable_metrics():
    report = build_report()
    authority = report["authority"]
    assert authority["reviewed_pairs"] == 55
    assert authority["accept_hit"] + authority["accept_miss"] > 0
    assert authority["reject_hit"] + authority["reject_avoided"] > 0
    assert report["accepted_pair_diagnosis"]
    assert report["correct_match_score_distribution"]
    assert [row["floor"] for row in report["candidate_floor_sweep"]] == [
        0.55,
        0.60,
        0.65,
        0.70,
        0.75,
        0.80,
        0.85,
    ]
