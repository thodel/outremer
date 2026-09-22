"""The weekly OCR canary (evaluation/ocr_canary.py), judged offline.

Two lessons are pinned here. The first version shelled out to pytest, which
the tei venv does not have (lockfile only): it failed on "No module named
pytest" and raised a false alert. And its judgement compared CER against the
edition with CER against a control five times shorter — CER divides by the
reference length, so any long output passed, including the control repeated.
"""

import json
import random

from evaluation import _pipeline, ocr_canary

REFERENCE = ocr_canary.REFERENCE.read_text(encoding="utf-8")
# qwen3.8-27b on the hi-res fixture, tei 2026-09-22 (thinking off): the
# address clause, abbreviated, before the output degenerates into "w. w. w.".
REAL_READING = (
    "IN NOMINE D. A. Amen. Rex H. formann. Aque 7 Comites And. Aring. Episc. "
    "Hinz. Comes. Baromb. Iulie. Lond. 7. Vicecomitib. D. prepositis. Comitat. "
    "et omnib Ballivis 7 feoffis suis Sal. D. nari nol.\n"
    "p. w. w. Venab. pr. w. w. Steph. Cant. Archiep. T. Angl. Pr."
)
LOOP = " w." * 4000


def test_fixture_and_reference_exist():
    assert ocr_canary.FIXTURE.is_file() and ocr_canary.FIXTURE.suffix == ".pdf"
    assert len(ocr_canary._words(REFERENCE)) > 50


def test_the_real_abbreviated_reading_passes():
    verdict = ocr_canary.judge(REAL_READING, REFERENCE)
    assert verdict["ok"], verdict
    assert {"episc", "archiep", "prepositis", "uicecomitib"} <= set(verdict["attested"])
    assert verdict["control_words"] == 0


def test_a_repetition_loop_neither_passes_alone_nor_inflates_a_reading():
    assert not ocr_canary.judge(LOOP, REFERENCE)["ok"]
    alone = ocr_canary.judge(REAL_READING, REFERENCE)
    looped = ocr_canary.judge(REAL_READING + LOOP, REFERENCE)
    assert looped["charter_words"] == alone["charter_words"]
    assert looped["repeat_share"] > 0.9 > alone["repeat_share"]  # flagged, not failed


def test_length_cannot_buy_a_pass():
    """The CER version passed these: long text looked closer to the longer
    reference regardless of content."""
    random.seed(1)
    noise = "".join(random.choice("abcdefghilmnoprstu ") for _ in range(12000))
    assert not ocr_canary.judge(noise, REFERENCE)["ok"]
    assert not ocr_canary.judge(ocr_canary.CONTROL * 5, REFERENCE)["ok"]


def test_prose_about_the_page_fails():
    description = (
        "This image shows a medieval charter written in Latin on parchment. The "
        "handwriting is a dense chancery script with many abbreviations. It "
        "appears to be the Magna Carta, granted by King John to his barons. "
    ) * 3
    assert not ocr_canary.judge(description, REFERENCE)["ok"]


def test_generic_charter_latin_alone_is_not_enough():
    formula = (
        "In nomine sancte et individue trinitatis amen. Notum sit omnibus Christi "
        "fidelibus tam presentibus quam futuris quod ego dedi et concessi deo et "
        "ecclesie beate Marie. "
    ) * 2
    verdict = ocr_canary.judge(formula, REFERENCE)
    assert not verdict["ok"] and verdict["charter_words"] < ocr_canary.MIN_ATTESTED


def test_empty_output_and_bail_out_tokens_fail():
    """How recognition failed for two weeks: HTTP 200, no text (#142)."""
    assert not ocr_canary.judge("", REFERENCE)["ok"]
    assert not ocr_canary.judge("[NOT_A_PAGE]", REFERENCE)["ok"]
    assert not ocr_canary.judge("[illegible]", REFERENCE)["ok"]


def test_main_prints_the_verdict_the_healthcheck_greps_for(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(_pipeline, "recognise", lambda pdf: (REAL_READING, {"qwen3-vl": 1}))
    saved = tmp_path / "ocr-canary.txt"
    assert ocr_canary.main(["--save", str(saved)]) == 0
    out = capsys.readouterr().out
    assert '"canary": "pass"' in out  # the healthcheck's grep, verbatim
    assert json.loads(out)["engines"] == {"qwen3-vl": 1}
    assert saved.read_text(encoding="utf-8") == REAL_READING

    monkeypatch.setattr(_pipeline, "recognise", lambda pdf: ("", {}))
    assert ocr_canary.main([]) == 1
    assert json.loads(capsys.readouterr().out)["canary"] == "fail"
