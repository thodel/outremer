"""Tests for pipeline run-report provenance."""

import json

from run_pipeline import _write_run_report


def test_run_report_records_resolved_model_roles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    roles = {
        "VISION": "vision-model",
        "TEXT": "text-model",
        "ORCH": "orchestrator-model",
    }

    _write_run_report(
        run_at="2026-07-30T09:00:00+00:00",
        docs_total=1,
        docs_ok=1,
        docs_failed=0,
        total_persons=2,
        extraction_model=roles["TEXT"],
        model_roles=roles,
        ocr_engine="qwen3-vl",
        failures=[],
    )

    report = json.loads((tmp_path / "data/staging/run_report.json").read_text())
    assert report["model_roles"] == roles
