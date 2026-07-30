from evaluation.authority_enrichment_report import build_report


def test_epic19_report_contains_comparable_metrics():
    report = build_report()
    authority = report["authority"]
    assert authority["reviewed_pairs"] == 55
    assert authority["accept_hit"] + authority["accept_miss"] > 0
    assert authority["reject_hit"] + authority["reject_avoided"] > 0
    assert report["accepted_pair_diagnosis"]
    assert report["correct_match_score_distribution"]
    audit = report["accepted_authority_pair_audit"]
    assert len(audit) == 7
    suspicious = {
        (row["mention"], row["authority_id"], row["authority_label"])
        for row in audit
        if row["status"] == "needs_scholarly_review"
    }
    assert ("Ekkehard", "AUTH:CR14", "Erard I of Brienne") in suspicious
    assert ("Fulcher of Chartres", "AUTH:CR33", "Charles of Denmark") in suspicious
    assert [row["floor"] for row in report["candidate_floor_sweep"]] == [
        0.55,
        0.60,
        0.65,
        0.70,
        0.75,
        0.80,
        0.85,
    ]
