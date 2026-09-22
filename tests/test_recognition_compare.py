"""M14.5 (#124) recognition comparison — offline, with fake engines.

The fakes mirror the production contract: ``_pipeline.vlm_ocr`` returns
``(text, model id)``, and the ATR client is a context manager whose
``transcribe`` returns an object shaped like ``atr_client.AtrResult``.
"""

import io
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from evaluation import _pipeline, recognition_compare

SCANS = Path(__file__).resolve().parent / "fixtures" / "scans"
PAGE = SCANS / "magna-carta-1215-incipit-page.pdf"  # 1230×820, page-shaped
STRIP = SCANS / "magna-carta-1215-incipit-hires.pdf"  # 4680×820, a line strip


@dataclass(frozen=True)
class _Result:  # the fields of atr_client.AtrResult
    text: str
    confidence: float
    model: str
    engine: str
    service_version: str = "0.1.0"


class _FakeAtr:
    calls: list = []

    def __init__(self, outcomes):
        self.outcomes = outcomes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_models(self):
        return [
            {"id": "catmus", "zenodo_id": "10.5281/zenodo.7516057", "hf_repo": None},
            {"id": "essoins", "zenodo_id": None, "hf_repo": "dh-unibe/trocr-essoins"},
        ]

    def transcribe(self, image, *, model, engine):
        _FakeAtr.calls.append((engine, model, len(image)))
        outcome = self.outcomes[model]
        if isinstance(outcome, Exception):
            raise outcome
        return _Result(text=outcome, confidence=0.5, model=model, engine=engine)


@pytest.fixture
def outcomes(monkeypatch):
    _FakeAtr.calls = []
    table = {"catmus": "Johannes dei gracia rex anglie", "essoins": "Johannes dei gratia rex"}
    monkeypatch.setattr(
        _pipeline, "vlm_ocr", lambda pdf: ("Johannes Dei gratia rex Anglie", "qwen3.8-27b")
    )
    monkeypatch.setattr(_pipeline, "atr_client", lambda: _FakeAtr(table))
    return table


def test_page_fixture_is_image_only_and_page_shaped():
    assert not (PdfReader(str(PAGE)).pages[0].extract_text() or "").strip()
    width, height = Image.open(io.BytesIO(_pipeline.page_image(PAGE))).size
    assert (width, height) == (1230, 820)
    assert max(width, height) / min(width, height) <= recognition_compare.MAX_ATR_ASPECT
    # Same line height as the hi-res fixture it is cut from (~62 px/line).
    assert height / 12 >= 50


def test_each_transcript_is_stored_with_its_engine_provenance(outcomes, tmp_path):
    prov = recognition_compare.compare(
        PAGE, ["vlm", "kraken:catmus", "trocr:essoins"], tmp_path
    )

    by_spec = {record["spec"]: record for record in prov["engines"]}
    assert set(by_spec) == {"vlm", "kraken:catmus", "trocr:essoins"}
    assert by_spec["vlm"] | {"seconds": 0} == {
        "engine": "vlm", "backend": "gpustack", "model": "qwen3.8-27b",
        "seconds": 0, "chars": 30, "spec": "vlm", "file": "vlm.txt",
    }
    assert by_spec["kraken:catmus"]["backend"] == "atr-gateway"
    assert by_spec["kraken:catmus"]["service_version"] == "0.1.0"
    assert by_spec["kraken:catmus"]["weights"] == {"zenodo_id": "10.5281/zenodo.7516057"}
    assert by_spec["trocr:essoins"]["weights"] == {"hf_repo": "dh-unibe/trocr-essoins"}
    assert (tmp_path / "kraken__catmus.txt").read_text() == outcomes["catmus"]
    # The gateway received the page's own image bytes, once per ATR engine.
    assert [(e, m) for e, m, _ in _FakeAtr.calls] == [("kraken", "catmus"), ("trocr", "essoins")]
    assert prov["input"]["page_image"] == {"width": 1230, "height": 820}
    assert len(prov["input"]["sha256"]) == 64
    pairs = prov["candidate_distance"]["pairwise"]
    assert len(pairs) == 3 and all(0.0 <= p["distance"] <= 1.0 for p in pairs)
    assert json.loads((tmp_path / "provenance.json").read_text()) == prov


def test_a_strip_is_refused_before_anything_reaches_the_gateway(outcomes, tmp_path):
    with pytest.raises(ValueError, match="a strip, not a page"):
        recognition_compare.compare(STRIP, ["vlm", "kraken:catmus"], tmp_path)
    assert _FakeAtr.calls == []
    assert not (tmp_path / "vlm.txt").exists(), "refused before running any engine"
    rc = recognition_compare.main(
        [str(STRIP), "--engine", "kraken:catmus", "--out", str(tmp_path)]
    )
    assert rc == 2


def test_a_strip_may_still_go_to_the_vlm(outcomes, tmp_path):
    prov = recognition_compare.compare(STRIP, ["vlm"], tmp_path)
    assert prov["engines"][0]["chars"] > 0


def test_a_failing_engine_is_recorded_and_the_rest_still_measured(outcomes, tmp_path):
    outcomes["essoins"] = RuntimeError("ATR gateway returned 502 at /ocr")
    rc = recognition_compare.main(
        [str(PAGE), "--engine", "vlm", "--engine", "trocr:essoins", "--out", str(tmp_path)]
    )
    assert rc == 1
    prov = json.loads((tmp_path / "provenance.json").read_text())
    failed = [record for record in prov["engines"] if "error" in record]
    assert [record["spec"] for record in failed] == ["trocr:essoins"]
    assert "502" in failed[0]["error"]
    assert (tmp_path / "vlm.txt").exists()
    assert prov["candidate_distance"]["pairwise"] == []  # one usable transcript


def test_an_empty_transcription_counts_as_a_failure(monkeypatch, outcomes, tmp_path):
    """Empty is how the VLM path failed silently for two weeks (#141)."""
    monkeypatch.setattr(_pipeline, "vlm_ocr", lambda pdf: ("", "qwen3.8-27b"))
    rc = recognition_compare.main(
        [str(PAGE), "--engine", "vlm", "--engine", "kraken:catmus", "--out", str(tmp_path)]
    )
    assert rc == 1
    prov = json.loads((tmp_path / "provenance.json").read_text())
    assert prov["engines"][0]["error"] == "empty transcription"
    assert prov["candidate_distance"]["pairwise"] == []


def test_an_atr_engine_needs_a_model_id(tmp_path):
    with pytest.raises(ValueError, match="<engine>:<model-id>"):
        recognition_compare.compare(PAGE, ["kraken"], tmp_path)
