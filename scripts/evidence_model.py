#!/usr/bin/env python3
"""Operational helpers for the evidence-first v1 canonical contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
OBJECT_TYPES = {
    "source_work", "manifestation", "snapshot", "passage", "mention", "assertion",
    "person", "group", "identity_hypothesis", "decision", "activity",
}


class EvidenceContractError(ValueError):
    pass


def stable_id(kind: str, *parts: str) -> str:
    """Deterministic local ID; source-native IDs remain separate properties."""
    if kind not in OBJECT_TYPES:
        raise EvidenceContractError(f"unknown object type: {kind}")
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]
    return f"outremer:{kind}:{digest}"


def object_index(dataset: dict) -> dict[str, dict]:
    return {obj["id"]: obj for obj in dataset.get("objects", [])}


def validate_dataset(dataset: dict) -> list[str]:
    errors: list[str] = []
    if dataset.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    objects = dataset.get("objects")
    if not isinstance(objects, list):
        return errors + ["objects must be an array"]
    ids = [obj.get("id") for obj in objects]
    if None in ids or len(ids) != len(set(ids)):
        errors.append("object ids must be present and unique")
    index = object_index(dataset)
    for obj in objects:
        kind = obj.get("type")
        if kind not in OBJECT_TYPES:
            errors.append(f"{obj.get('id')}: unknown type {kind}")
            continue
        if not isinstance(obj.get("version"), int) or obj["version"] < 1:
            errors.append(f"{obj['id']}: version must be a positive integer")
        if obj.get("supersedes") and obj["supersedes"] not in index:
            errors.append(f"{obj['id']}: missing superseded object")
        if kind == "passage" and obj.get("snapshot_id") not in index:
            errors.append(f"{obj['id']}: passage requires snapshot")
        if kind == "mention":
            if obj.get("passage_id") not in index:
                errors.append(f"{obj['id']}: mention requires passage")
            if not obj.get("verbatim"):
                errors.append(f"{obj['id']}: mention requires verbatim text")
        if kind == "assertion":
            passages = obj.get("passage_ids", [])
            if not passages or any(item not in index for item in passages):
                errors.append(f"{obj['id']}: assertion requires evidence passage(s)")
        if kind == "identity_hypothesis":
            if obj.get("mention_id") not in index:
                errors.append(f"{obj['id']}: hypothesis requires mention")
            for candidate in obj.get("candidates", []):
                if candidate.get("identity_id") not in index:
                    errors.append(f"{obj['id']}: unknown identity candidate")
        if kind == "decision":
            for field in ("hypothesis_id", "candidate_id", "activity_id"):
                if obj.get(field) not in index:
                    errors.append(f"{obj['id']}: decision requires {field}")
    return errors


def import_snapshot(
    dataset: dict, snapshot: dict, generated_objects: list[dict]
) -> dict:
    """Idempotently add a snapshot and its objects without merging identities."""
    existing = object_index(dataset)
    snapshot_id = snapshot["id"]
    if snapshot_id in existing:
        if existing[snapshot_id].get("checksum") != snapshot.get("checksum"):
            raise EvidenceContractError("snapshot id reused with a different checksum")
        return dataset
    additions = [snapshot, *generated_objects]
    duplicate = set(existing) & {obj["id"] for obj in additions}
    if duplicate:
        raise EvidenceContractError(f"generated ids already exist: {sorted(duplicate)}")
    result = {
        "schema_version": SCHEMA_VERSION,
        "objects": [*dataset.get("objects", []), *additions],
    }
    errors = validate_dataset(result)
    if errors:
        raise EvidenceContractError("; ".join(errors))
    return result


def canonical_bytes(dataset: dict) -> bytes:
    return (json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
