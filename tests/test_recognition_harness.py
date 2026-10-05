"""Tests for M15.3 — recognition metrics wired into harness and history."""

import json

import pytest

from evaluation import harness


def test_evaluate_fixture_returns_recognition_from_selection_json(
    tmp_path, monkeypatch
):
    """When a recognition/selection.json exists for a doc, it is parsed and
    attached as result["recognition"] with coverage + selection_agreement."""
    fixture = {
        "doc_id": "magna-carta-1215-incipit-page",
        "mode": "adjudicated",
        "accepted": [["Guillaume", "AUTH:CR1"]],
        "rejected": [],
        "predictions": {"persons": ["Guillaume"], "links": []},
    }
    rec_dir = tmp_path / "evaluation" / "recognition" / "magna-carta-1215-incipit-page"
    rec_dir.mkdir(parents=True)
    events = [
        {
            "candidates": ["ecclesia", "ecela"],
            "automatic_selection": "ecclesia",
            "human_selection": "ecclesia",
        },
        {
            "candidates": ["suspendatur", "suspende"],
            "automatic_selection": "suspende",
            "human_selection": "suspendatur",
        },
    ]
    (rec_dir / "selection.json").write_text(json.dumps(events))

    monkeypatch.setattr(harness, "REPO_ROOT", tmp_path)

    result = harness.evaluate_fixture(fixture)
    assert "recognition" in result
    rec = result["recognition"]
    assert rec["events"] == 2
    assert rec["covered"] == 2
    assert rec["coverage"] == 1.0
    assert rec["comparable_selections"] == 2
    assert rec["automatic_matches"] == 1
    assert rec["selection_agreement"] == 0.5


def test_evaluate_fixture_returns_no_recognition_field_when_dir_absent(tmp_path, monkeypatch):
    """No recognition directory → recognition field is absent (not null)."""
    fixture = {
        "doc_id": "no-such-doc",
        "mode": "adjudicated",
        "accepted": [],
        "rejected": [],
        "predictions": {"persons": [], "links": []},
    }
    monkeypatch.setattr(harness, "REPO_ROOT", tmp_path)

    result = harness.evaluate_fixture(fixture)
    assert "recognition" not in result


def test_append_history_writes_recognition_tail(tmp_path):
    """When any fixture has recognition data, _append_history writes
    recognition_tail into the history entry (M15.3)."""
    doc_results = {
        "doc-A": {
            "mode": "adjudicated",
            "recognition": {
                "events": 3,
                "covered": 2,
                "coverage": 2 / 3,
                "selection_agreement": 0.5,
            },
        }
    }
    hist_file = tmp_path / "eval_history.jsonl"
    harness._append_history(
        hist_file, doc_results, aggregate=0.9, seg_totals={}, seg_gold={}
    )

    entry = json.loads(hist_file.read_text())
    assert "recognition_tail" in entry
    assert "doc-A" in entry["recognition_tail"]
    assert entry["recognition_tail"]["doc-A"]["coverage"] == pytest.approx(2 / 3)
    assert entry["recognition_tail"]["doc-A"]["selection_agreement"] == 0.5


def test_append_history_omits_recognition_tail_when_no_recognition(tmp_path):
    """No recognition data in any fixture → no recognition_tail in history."""
    doc_results = {
        "doc-X": {
            "mode": "adjudicated",
            # no recognition key
        }
    }
    hist_file = tmp_path / "eval_history.jsonl"
    harness._append_history(
        hist_file, doc_results, aggregate=0.9, seg_totals={}, seg_gold={}
    )
    entry = json.loads(hist_file.read_text())
    assert "recognition_tail" not in entry


def test_format_report_includes_recognition_columns():
    """format_report() renders cov + sel columns (M15.3)."""
    from evaluation.metrics import format_report

    doc_results = {
        "test-doc": {
            "mode": "adjudicated",
            "extraction": {"precision": 0.8, "recall": 0.75, "f1": 0.77},
            "recognition": {"coverage": 0.9, "selection_agreement": 0.75},
        }
    }
    report = format_report(doc_results)
    lines = report.splitlines()
    header = lines[0]
    data   = lines[2]
    assert "cov" in header
    assert "sel" in header
    assert "  0.9" in data        # coverage right-aligned in 6 chars
    assert " 0.75" in data        # selection right-aligned in 6 chars


def test_format_report_shows_dash_when_recognition_absent():
    """Docs without recognition show em-dash in cov/sel columns."""
    from evaluation.metrics import format_report

    doc_results = {
        "bare-doc": {
            "mode": "adjudicated",
            "extraction": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            # no recognition
        }
    }
    report = format_report(doc_results)
    # The two right-most data columns (cov, sel) should be '—'
    fields = report.split()
    # Fields are whitespace-separated; bare-doc is first; cov/sel are last two
    assert fields[-1] == "—"   # sel
    assert fields[-2] == "—"   # cov
