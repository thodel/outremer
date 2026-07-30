import json

from evaluation import harness


def test_repeat_report_contains_mean_and_observed_range(tmp_path):
    output = tmp_path / "repeat.json"
    assert harness.main(["--repeat", "3", "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["uncertainty"]["samples"] == 3
    assert report["uncertainty"]["min"] == report["uncertainty"]["max"]
    assert len(report["samples"]) == 3


def test_repeat_gate_uses_lower_observed_bound(monkeypatch, tmp_path):
    values = iter([0.90, 0.80])
    original = harness.evaluate_fixture

    def variable_sample(fixture, **kwargs):
        result = original(fixture, **kwargs)
        if "linking" in result:
            agreement = next(values)
            result["linking"] = {
                "reviewed_pairs": 10,
                "accept_hit": round(agreement * 10),
                "accept_miss": 10 - round(agreement * 10),
                "reject_hit": 0,
                "reject_avoided": 0,
                "agreement": agreement,
            }
        return result

    fixture = {
        "doc_id": "sample",
        "mode": "adjudicated",
        "accepted": [["Name", "AUTH:1"]],
        "predictions": {"persons": ["Name"], "links": []},
    }
    (tmp_path / "sample.json").write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(harness, "evaluate_fixture", variable_sample)
    assert harness.main([
        "--fixtures", str(tmp_path),
        "--repeat", "2",
        "--min-agreement", "0.85",
    ]) == 1
