import json

from run_pipeline import sync_feedback_from_human_review


def _write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_decision_subtype_aggregation_counts_as_reject(tmp_path):
    feedback_path = tmp_path / "entity_feedback.json"
    decisions_path = tmp_path / "decisions.json"

    _write_json(
        decisions_path,
        [
            {"doc_id": "d1", "person": "See", "decision": "reject:wrong_match"},
            {"doc_id": "d1", "person": "See", "decision": "reject:wrong_era"},
        ],
    )

    stats = sync_feedback_from_human_review(
        feedback_path,
        decisions_path,
        min_reject_votes=2,
        min_accept_votes=1,
    )
    feedback = _read_json(feedback_path)

    assert stats["blocked_added"] == 1
    assert "See" in feedback["blocked_terms"]


def test_feedback_sync_threshold_transitions_and_precedence(tmp_path):
    feedback_path = tmp_path / "entity_feedback.json"
    decisions_path = tmp_path / "decisions.json"

    # Step 1: below reject threshold -> not blocked
    _write_json(decisions_path, [{"doc_id": "d1", "person": "Dei", "decision": "reject:wrong_match"}])
    sync_feedback_from_human_review(feedback_path, decisions_path, min_reject_votes=2, min_accept_votes=1)
    feedback = _read_json(feedback_path)
    assert "Dei" not in feedback["blocked_terms"]

    # Step 2: reaches reject threshold -> blocked
    _write_json(
        decisions_path,
        [
            {"doc_id": "d1", "person": "Dei", "decision": "reject:wrong_match"},
            {"doc_id": "d1", "person": "Dei", "decision": "reject:wrong_era"},
        ],
    )
    sync_feedback_from_human_review(feedback_path, decisions_path, min_reject_votes=2, min_accept_votes=1)
    feedback = _read_json(feedback_path)
    assert "Dei" in feedback["blocked_terms"]

    # Step 3: accepts >= rejects -> moved to allow_terms and removed from blocked_terms
    _write_json(
        decisions_path,
        [
            {"doc_id": "d1", "person": "Dei", "decision": "reject:wrong_match"},
            {"doc_id": "d1", "person": "Dei", "decision": "reject:wrong_era"},
            {"doc_id": "d1", "person": "Dei", "decision": "accept"},
            {"doc_id": "d1", "person": "Dei", "decision": "accept"},
        ],
    )
    sync_feedback_from_human_review(feedback_path, decisions_path, min_reject_votes=2, min_accept_votes=1)
    feedback = _read_json(feedback_path)
    assert "Dei" in feedback["allow_terms"]
    assert "Dei" not in feedback["blocked_terms"]
