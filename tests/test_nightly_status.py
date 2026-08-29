"""Tests for scripts/nightly_status.py (#115 observability)."""

import json

from nightly_status import build_status


def test_status_collects_run_gate_and_history(tmp_path):
    rr = tmp_path / "run_report.json"
    rr.write_text(json.dumps({
        "run_at": "2026-08-29T01:15:00+00:00", "docs_total": 3, "docs_failed": 0,
        "total_persons": 353, "llm_provider": "gpustack",
        "extraction_model": "qwen3.8-27b", "extraction_seed": 42,
        "extraction": {"documents_by_engine": {"gpustack": 3},
                        "degradation": {"fallback_chunks": 0}},
        "noise": {"noise_share": 0.21},
    }))
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({"status": "pass", "errors": []}))
    hist = tmp_path / "hist.jsonl"
    hist.write_text('{"run_at": "x", "combined_agreement": 0.9014, "segments": {}}\n')

    s = build_status(rr, gate, hist)
    assert s["run"]["documents_by_engine"] == {"gpustack": 3}
    assert s["run"]["fallback_chunks"] == 0
    assert s["gate"]["status"] == "pass"
    assert s["evaluation"]["combined_agreement"] == 0.9014


def test_status_survives_missing_inputs(tmp_path):
    s = build_status(tmp_path / "nope.json", tmp_path / "nope2.json", None)
    assert s["run"] is None and s["gate"] is None and s["evaluation"] is None
    assert "generated_at" in s
