#!/usr/bin/env python3
"""Append-only review decisions for assertions and identity hypotheses."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

TARGET_TYPES = {"assertion", "identity_hypothesis"}
ACTIONS = {"accept", "reject", "flag", "supersede"}


def pseudonym(reviewer: str) -> str:
    return "reviewer-" + hashlib.sha256(reviewer.encode()).hexdigest()[:12]


def make_review(
    *,
    target_id: str,
    target_type: str,
    action: str,
    reviewer: str,
    comment: str,
    supersedes: str | None = None,
    timestamp: str | None = None,
) -> dict:
    if target_type not in TARGET_TYPES:
        raise ValueError(f"unsupported target type: {target_type}")
    if action not in ACTIONS:
        raise ValueError(f"unsupported review action: {action}")
    if action == "supersede" and not supersedes:
        raise ValueError("supersede requires the prior decision id")
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    reviewer_id = pseudonym(reviewer)
    token = "\x1f".join((target_id, action, reviewer_id, timestamp, supersedes or ""))
    return {
        "id": "outremer:review:" + hashlib.sha256(token.encode()).hexdigest()[:24],
        "target_id": target_id,
        "target_type": target_type,
        "action": action,
        "reviewer": reviewer_id,
        "timestamp": timestamp,
        "comment": comment,
        "supersedes": supersedes,
    }


def append_review(path: Path, review: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(review, ensure_ascii=False, sort_keys=True) + "\n")


def review_state(reviews: list[dict], target_id: str) -> dict:
    """Keep concurrent reviewer disagreement visible; never pick a silent winner."""
    relevant = [review for review in reviews if review["target_id"] == target_id]
    superseded = {
        review["supersedes"] for review in relevant if review.get("supersedes")
    }
    active = [review for review in relevant if review["id"] not in superseded]
    actions = {review["action"] for review in active}
    return {
        "target_id": target_id,
        "history": relevant,
        "active": active,
        "conflict": "accept" in actions and bool(actions & {"reject", "flag"}),
    }
