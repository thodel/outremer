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
        extraction_seed=42,
        ocr_engine="qwen3-vl",
        failures=[],
        recognition_engines=dict(run_pipeline._recognition_engines_used),
    )
    report = json.loads(
        (tmp_path / "data" / "staging" / "run_report.json").read_text(encoding="utf-8")
    )
    assert report["recognition"]["engines_used"] == {"qwen3-vl": 1}


HIRES_FIXTURE = FIXTURE.parent / "magna-carta-1215-incipit-hires.pdf"
REFERENCE = FIXTURE.parent / "magna-carta-1215-incipit.reference.txt"
# Unrelated control: modern English scholarly prose, same order of magnitude.
CONTROL = (
    "The Popes and the Crusades. The First Crusade was the work of Pope Urban "
    "the Second, and the movement remained under papal direction throughout "
    "the twelfth and thirteenth centuries, as the letters of the popes show."
)


def test_hires_fixture_has_no_text_layer_and_a_legible_line_height():
    reader = PdfReader(str(HIRES_FIXTURE))
    assert len(reader.pages) == 1
    assert not (reader.pages[0].extract_text() or "").strip()
    # ~12 charter lines in this band; the 1280px derivative gives ~11 px/line,
    # which no engine can read (#124). Guard the property that matters.
    image = list(reader.pages[0].images)[0]
    from io import BytesIO

    from PIL import Image

    height = Image.open(BytesIO(image.data)).size[1]
    assert height / 12 >= 50, f"line height {height / 12:.0f}px is too coarse"


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


@pytest.mark.live_backend
@pytest.mark.skipif(
    os.environ.get("OUTREMER_LIVE_OCR") != "1",
    reason="set OUTREMER_LIVE_OCR=1 to exercise the live GPUStack backend",
)
def test_live_hires_recognition_reads_this_charter_not_noise():
    """A real quality gate, not a sign of life.

    The hand is hard and the transcription is heavily garbled — "Johannes Dei
    gracia" does not survive, though "Steph… Archiep" (Stephen Langton, in the
    witness list) does. Exact substring matching is therefore too brittle.
    Instead: the output must be closer to THIS charter's published text than to
    unrelated prose. That tolerates character noise while still failing on
    refusal ("[NOT_A_PAGE]"), empty output, or engine noise.

    Absolute CER is legitimate here because the reference is an independent
    scholarly edition — not a Human-in-the-Loop selection (see
    evaluation/README.md).
    """
    from evaluation.metrics import cer

    run_pipeline._recognition_engines_used.clear()
    text = run_pipeline.read_input(HIRES_FIXTURE)

    assert len(text.strip()) > 500, f"only {len(text.strip())} chars recognised"
    reference = REFERENCE.read_text(encoding="utf-8")
    d_charter = cer(reference, text)
    d_control = cer(CONTROL, text)
    assert d_charter < d_control, (
        f"transcription is no closer to the charter ({d_charter:.3f}) "
        f"than to unrelated prose ({d_control:.3f})"
    )


def test_page_images_extracted_as_image_data_urls():
    """The VLM path must send real image parts.

    The previous implementation base64-encoded the PDF into the TEXT prompt:
    measured against GPUStack on tei that produced 65k input tokens and HTTP
    400, and a vision model cannot read a blob of text tokens anyway.
    """
    urls = run_pipeline._page_images_as_data_urls(FIXTURE)
    assert urls, "fixture page carries an embedded image"
    assert urls[0].startswith("data:image/"), urls[0][:40]
    assert "application/pdf" not in urls[0]


def test_vlm_ocr_passes_images_not_text_blob(monkeypatch):
    seen = {}

    def fake_generate(prompt, *, model=None, images=None, **kw):
        seen["prompt"] = prompt
        seen["images"] = images
        return "Johannes Dei gratia rex Anglie"

    monkeypatch.setattr(run_pipeline, "_llm_generate", fake_generate)
    out = run_pipeline._qwen3vl_ocr(FIXTURE)

    assert out == "Johannes Dei gratia rex Anglie"
    assert seen["images"] and seen["images"][0].startswith("data:image/")
    assert "base64" not in seen["prompt"], "image must not ride in the text prompt"
    # No escape hatch of ANY kind: measured on this fixture the model answers
    # with whichever bail-out token the prompt offers ("[NOT_A_PAGE]",
    # "[illegible]") instead of attempting the hand.
    assert "NOT_A_PAGE" not in seen["prompt"]
    assert "illegible" not in seen["prompt"].lower()


def test_vlm_ocr_returns_empty_when_no_page_image(monkeypatch, tmp_path):
    monkeypatch.setattr(run_pipeline, "_page_images_as_data_urls", lambda p, **k: [])
    called = {"n": 0}
    monkeypatch.setattr(run_pipeline, "_llm_generate",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "x")
    assert run_pipeline._qwen3vl_ocr(FIXTURE) == ""
    assert called["n"] == 0, "must not call the model without an image"
