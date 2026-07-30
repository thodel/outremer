import json
import os
from pathlib import Path

import pytest
from pypdf import PdfReader

from scripts import run_pipeline

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "scans"
    / "magna-carta-1215-image-only.pdf"
)


def test_fixture_has_no_text_layer():
    reader = PdfReader(str(FIXTURE))
    assert len(reader.pages) == 1
    assert not (reader.pages[0].extract_text() or "").strip()


def test_image_only_pdf_routes_to_recognition_and_records_engine(monkeypatch, tmp_path):
    run_pipeline._recognition_engines_used.clear()
    monkeypatch.setattr(
        run_pipeline,
        "_qwen3vl_ocr",
        lambda path: "Johannes Dei gratia rex Anglie",
    )
    monkeypatch.setattr(run_pipeline, "_mistral_ocr", lambda path: "")

    text = run_pipeline.read_input(FIXTURE)

    assert text == "Johannes Dei gratia rex Anglie"
    assert run_pipeline._recognition_engines_used == {"qwen3-vl": 1}

    monkeypatch.chdir(tmp_path)
    run_pipeline._write_run_report(
        run_at="2026-07-30T08:00:00+00:00",
        docs_total=1,
        docs_ok=1,
        docs_failed=0,
        total_persons=0,
        extraction_model="test",
        ocr_engine="qwen3-vl",
        failures=[],
        recognition_engines=dict(run_pipeline._recognition_engines_used),
    )
    report = json.loads(
        (tmp_path / "data" / "staging" / "run_report.json").read_text(encoding="utf-8")
    )
    assert report["recognition"]["engines_used"] == {"qwen3-vl": 1}


@pytest.mark.live_backend
@pytest.mark.skipif(
    os.environ.get("OUTREMER_LIVE_OCR") != "1",
    reason="set OUTREMER_LIVE_OCR=1 to exercise the live GPUStack backend",
)
def test_live_image_only_pdf_returns_non_empty_text():
    run_pipeline._recognition_engines_used.clear()
    text = run_pipeline.read_input(FIXTURE)
    assert text.strip()
    assert sum(run_pipeline._recognition_engines_used.values()) == 1
