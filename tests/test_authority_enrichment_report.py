from evaluation.authority_enrichment_report import build_report


def test_epic19_report_contains_comparable_metrics():
    report = build_report()
    authority = report["authority"]
    # 58 pairs after the M19.0 repair; 71 after M19.2 tranche A added ten
    # accepts against the new records and three rejects for medium-band
    # string-similarity errors they exposed (#92).
    assert authority["reviewed_pairs"] == 71
    assert authority["accept_hit"] + authority["accept_miss"] == 14
    assert authority["reject_hit"] + authority["reject_avoided"] == 57
    assert report["accepted_pair_diagnosis"]
    assert report["correct_match_score_distribution"]
    audit = report["accepted_authority_pair_audit"]
    assert len(audit) == 14
    assert [row["floor"] for row in report["candidate_floor_sweep"]] == [
        0.55,
        0.60,
        0.65,
        0.70,
        0.75,
        0.80,
        0.85,
    ]


def test_no_accepted_pair_without_an_attested_name():
    """M19.0 (#97): the gate that keeps wrong-person accepts out of the gold.

    #98 found six of seven accepted pairs naming a different person than the
    authority record (Fulcher of Chartres → Charles of Denmark, …). Every
    accepted pair must now match a recorded name form of its target; a new
    accept that does not is a regression, not scholarly nuance — relink it
    or add the variant with provenance first.
    """
    report = build_report()
    unattested = [
        (row["mention"], row["authority_id"], row["authority_label"])
        for row in report["accepted_authority_pair_audit"]
        if row["status"] != "attested"
    ]
    assert unattested == [], unattested
