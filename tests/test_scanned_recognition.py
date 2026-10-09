import json
import logging
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
    """A real quality gate, not a sign of life — the same one the tei canary runs.

    The hand is hard and the transcription heavily abbreviated and garbled —
    "Johannes Dei gracia" does not survive, "Vicecomitib. … prepositis …
    Ballivis" and "Steph. Cant. Archiep." do. So the gate asks whether the
    output attests THIS charter's vocabulary (abbreviations allowed), counted
    in distinct words so that a runaway repetition loop cannot pass by volume,
    and fails on refusal, empty output, noise, or unrelated prose. See
    evaluation/ocr_canary.py for why a CER comparison could not do this.
    """
    from evaluation.ocr_canary import judge  # same judgement as the tei canary

    run_pipeline._recognition_engines_used.clear()
    text = run_pipeline.read_input(HIRES_FIXTURE)

    verdict = judge(text, REFERENCE.read_text(encoding="utf-8"))
    assert verdict["ok"], (
        f"attests {verdict['charter_words']} words of this charter and "
        f"{verdict['control_words']} of unrelated prose: {verdict['attested']}"
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


def test_vlm_ocr_raises_when_no_page_image(monkeypatch, tmp_path):
    monkeypatch.setattr(run_pipeline, "_page_images_as_data_urls", lambda p, **k: [])
    called = {"n": 0}
    monkeypatch.setattr(run_pipeline, "_llm_generate",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "x")
    with pytest.raises(run_pipeline.NoPageImage):
        run_pipeline._qwen3vl_ocr(FIXTURE)
    assert called["n"] == 0, "must not call the model without an image"


def test_vlm_ocr_sends_the_thinking_switch(monkeypatch):
    """qwen3.8-27b reasons before it answers. Without the switch the OCR call
    spent all 8192 tokens thinking and returned 0 characters (tei, 2026-09-21);
    with it, the same page came back as 12 378 characters of transcription."""
    import config

    monkeypatch.setattr(config, "QWEN3_VL_DISABLE_THINKING", True)
    seen = {}
    monkeypatch.setattr(run_pipeline, "_llm_generate",
                        lambda prompt, **kw: seen.update(kw) or "Johannes")
    run_pipeline._qwen3vl_ocr(FIXTURE)
    assert seen["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_vlm_ocr_thinking_switch_can_be_turned_off(monkeypatch):
    """For a non-reasoning vision model the switch is noise; allow omitting it."""
    import config

    monkeypatch.setattr(config, "QWEN3_VL_DISABLE_THINKING", False)
    seen = {}
    monkeypatch.setattr(run_pipeline, "_llm_generate",
                        lambda prompt, **kw: seen.update(kw) or "Johannes")
    run_pipeline._qwen3vl_ocr(FIXTURE)
    assert "extra_body" not in seen


@pytest.mark.skipif(
    "QWEN3_VL_DISABLE_THINKING" in os.environ
    or "EXTRACTION_DISABLE_THINKING" in os.environ,
    reason="explicitly configured in this environment",
)
def test_thinking_switches_are_on_unless_configured_off():
    """The only served text and vision model is a Qwen3 hybrid; a fresh
    checkout must not need an .env to get non-empty answers."""
    import config

    assert config.QWEN3_VL_DISABLE_THINKING is True
    assert config.EXTRACTION_DISABLE_THINKING is True


def test_vlm_ocr_fails_loudly_on_empty_content(monkeypatch, caplog):
    """Empty content is an HTTP 200. Silence made it look like a blank page;
    since #72 it is an error that names the likely cause."""
    monkeypatch.setattr(run_pipeline, "_llm_generate", lambda prompt, **kw: "")
    with caplog.at_level(logging.ERROR), pytest.raises(run_pipeline.RecognitionError) as ei:
        run_pipeline._qwen3vl_ocr(FIXTURE)
    assert "returned no text for magna-carta-1215-image-only.pdf" in caplog.text
    assert "QWEN3_VL_DISABLE_THINKING" in str(ei.value)


def test_unreachable_backend_fails_the_document_with_an_actionable_message(monkeypatch):
    """M14.2/#72: no backend → the document fails, it does not come back empty."""
    def down(*a, **k):
        raise ConnectionError("[Errno 111] Connection refused")

    monkeypatch.setattr(run_pipeline, "_llm_generate", down)
    run_pipeline._recognition_engines_used.clear()
    with pytest.raises(run_pipeline.RecognitionError) as ei:
        run_pipeline.read_input(FIXTURE)
    msg = str(ei.value)
    assert "magna-carta-1215-image-only.pdf needs recognition" in msg
    assert "Connection refused" in msg
    assert "GPUSTACK_BASE_URL" in msg
    assert run_pipeline._recognition_engines_used == {}


def test_short_text_pdf_without_page_image_keeps_its_text(monkeypatch, tmp_path):
    """A one-line text PDF is not a scan: nothing to recognise, keep the text."""
    import pypdf

    class FakePage:
        def extract_text(self):
            return "Short note."

    class FakeReader:
        def __init__(self, path):
            self.pages = [FakePage()]

    monkeypatch.setattr(pypdf, "PdfReader", FakeReader)
    monkeypatch.setattr(run_pipeline, "_page_images_as_data_urls", lambda p, **k: [])
    monkeypatch.setattr(run_pipeline, "_llm_generate",
                        lambda *a, **k: pytest.fail("must not call the model"))
    assert run_pipeline.read_input(tmp_path / "short.pdf") == "Short note."


def test_failed_recognition_lands_in_the_run_report(monkeypatch, tmp_path):
    """End to end through main(): docs_failed, the message, exit 1."""
    import sys

    def down(*a, **k):
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(run_pipeline, "_llm_generate", down)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(sys, "argv", [
        "run_pipeline.py", "--file", str(FIXTURE), "--site-dir", str(tmp_path / "site"),
        "--bib-dir", str(tmp_path / "bib"), "--evidence-dir", str(tmp_path / "evidence"),
        "--outremer-index", str(Path(run_pipeline.__file__).parent / "outremer_index.json"),
    ])
    assert run_pipeline.main() == 1
    report = json.loads((tmp_path / "data" / "staging" / "run_report.json").read_text())
    assert report["docs_total"] == 1 and report["docs_failed"] == 1 and report["docs_ok"] == 0
    assert "needs recognition" in report["failures"][0]["error"]
    assert "GPUSTACK_BASE_URL" in report["failures"][0]["error"]
    assert report["recognition"]["engines_used"] == {}
    assert not list((tmp_path / "site" / "data").glob("magna-carta*.json"))
