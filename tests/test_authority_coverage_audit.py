from pathlib import Path

from scripts.audit_authority_coverage import audit

ROOT = Path(__file__).resolve().parents[1]


def test_coverage_audit_exposes_named_and_tradition_gaps():
    report = audit(
        ROOT / "scripts" / "outremer_index.json",
        ROOT / "data" / "audits" / "epic19-benchmark-figures.json",
    )
    assert report["authority_records"] == 129
    rows = {row["preferred_label"]: row for row in report["figures"]}
    assert rows["Godfrey of Bouillon"]["status"] == "present"
    assert rows["Fulcher of Chartres"]["status"] == "missing"
    assert report["by_tradition"]["Arabic-Islamic"]["missing"] == 3
    assert report["by_tradition"]["Armenian"]["missing"] == 1
