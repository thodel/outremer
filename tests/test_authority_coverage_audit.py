from pathlib import Path

from scripts.audit_authority_coverage import audit

ROOT = Path(__file__).resolve().parents[1]


def test_coverage_audit_finds_every_benchmark_figure_after_tranche_a():
    """#99 found 1 of 14 present; M19.2 tranche A (#92) added the other 13."""
    report = audit(
        ROOT / "scripts" / "outremer_index.json",
        ROOT / "data" / "audits" / "epic19-benchmark-figures.json",
    )
    assert report["authority_records"] == 143
    rows = {row["preferred_label"]: row for row in report["figures"]}
    assert rows["Godfrey of Bouillon"]["status"] == "present"
    assert rows["Fulcher of Chartres"]["status"] == "present"
    assert report["summary"] == {"present": 14}
    for tradition, counts in report["by_tradition"].items():
        assert counts["missing"] == 0, tradition
