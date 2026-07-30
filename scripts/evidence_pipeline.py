#!/usr/bin/env python3
"""Build and validate evidence-first artifacts from production pipeline output."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evidence_model import SCHEMA_VERSION, canonical_bytes, stable_id, validate_dataset
from evidence_semantics import dataset_to_graph, validate_graph
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "evidence-first-v1.schema.json"
ADAPTER_VERSION = "pipeline-evidence-v1"


class EvidencePipelineError(ValueError):
    """Raised when production output cannot satisfy the canonical contract."""


def _timestamp(path: Path) -> str:
    """Stable snapshot timestamp for an unchanged local source file."""
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _identity(
    identity_id: str,
    label: str,
    *,
    group: bool = False,
    native_id: str | None = None,
) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": identity_id,
        "type": "group" if group else "person",
        "version": 1,
        "preferred_label": label,
    }
    if native_id:
        namespace, _, value = native_id.partition(":")
        obj["source_native_ids"] = {namespace.lower(): value or native_id}
    return obj


def build_evidence_dataset(
    *,
    in_path: Path,
    doc_id: str,
    text_sha256: str,
    metadata: dict[str, Any],
    persons: list[dict[str, Any]],
    links: list[dict[str, Any]],
    extraction_engine: dict[str, Any],
    language: str | None,
) -> dict[str, Any]:
    """Map one legacy pipeline document into the evidence-first v1 contract."""
    source_key = in_path.as_posix()
    work_id = stable_id("source_work", source_key)
    manifestation_id = stable_id("manifestation", source_key, in_path.suffix.lower())
    snapshot_id = stable_id("snapshot", source_key, text_sha256)
    activity_id = stable_id(
        "activity",
        doc_id,
        str(extraction_engine.get("provider") or "unknown"),
        str(extraction_engine.get("model") or "unknown"),
    )
    captured_at = _timestamp(in_path)
    title = str(metadata.get("title") or in_path.stem)
    citation_bits = [
        str(metadata.get(key)).strip()
        for key in ("author", "title", "year")
        if metadata.get(key)
    ]

    objects: list[dict[str, Any]] = [
        {"id": work_id, "type": "source_work", "version": 1, "title": title},
        {
            "id": manifestation_id,
            "type": "manifestation",
            "version": 1,
            "work_id": work_id,
            "citation": ", ".join(citation_bits) or in_path.name,
        },
        {
            "id": snapshot_id,
            "type": "snapshot",
            "version": 1,
            "manifestation_id": manifestation_id,
            "checksum": text_sha256,
            "retrieved_at": captured_at,
            "source_locator": source_key,
            "ingested_at": captured_at,
        },
        {
            "id": activity_id,
            "type": "activity",
            "version": 1,
            "activity_kind": "extraction",
            "agent": str(extraction_engine.get("provider") or "unknown"),
            "started_at": captured_at,
            "adapter_version": (
                f"{ADAPTER_VERSION}:{extraction_engine.get('model')}"
                if extraction_engine.get("model")
                else ADAPTER_VERSION
            ),
        },
    ]
    links_by_person = {str(item.get("person")): item for item in links}
    known_ids = {obj["id"] for obj in objects}

    def add(obj: dict[str, Any]) -> None:
        if obj["id"] not in known_ids:
            objects.append(obj)
            known_ids.add(obj["id"])

    for position, person in enumerate(persons):
        verbatim = str(person.get("raw_mention") or person.get("name") or "").strip()
        if not verbatim:
            continue
        group = bool(person.get("group"))
        offset = int(person.get("source_offset") or 0)
        context = str(person.get("context") or verbatim)
        passage_id = stable_id("passage", snapshot_id, str(offset), context)
        mention_id = stable_id("mention", passage_id, verbatim, str(position))
        provisional_id = stable_id(
            "group" if group else "person", doc_id, "extracted", verbatim, str(position)
        )
        assertion_id = stable_id("assertion", mention_id, "extracted-mention")
        confidence = max(0.0, min(1.0, float(person.get("confidence") or 0.0)))

        add(
            {
                "id": passage_id,
                "type": "passage",
                "version": 1,
                "snapshot_id": snapshot_id,
                "locator": f"character offset {offset}",
                "text": context,
            }
        )
        add(
            {
                "id": mention_id,
                "type": "mention",
                "version": 1,
                "passage_id": passage_id,
                "verbatim": verbatim,
                "language": language or metadata.get("language"),
                "script": None,
                "mention_kind": "group" if group else "person",
            }
        )
        add(_identity(provisional_id, str(person.get("name") or verbatim), group=group))
        add(
            {
                "id": assertion_id,
                "type": "assertion",
                "version": 1,
                "passage_ids": [passage_id],
                "subject_id": provisional_id,
                "predicate": "extracted_mention",
                "object": verbatim,
                "participants": [{"role": "mention_subject", "identity_id": provisional_id}],
                "semantics": {
                    "source_certainty": "unknown",
                    "polarity": "affirmed",
                    "inference": "extracted",
                    "source_reliability": "unassessed",
                    "review_status": "unreviewed",
                    "extractor_confidence": confidence,
                },
                "provenance": {
                    "snapshot_id": snapshot_id,
                    "generation_activity_id": activity_id,
                },
            }
        )

        link = links_by_person.get(str(person.get("name"))) or {}
        candidate_rows: list[dict[str, Any]] = []
        for candidate in link.get("candidates") or []:
            native_id = str(candidate.get("outremer_id") or "")
            label = str(candidate.get("outremer_name") or native_id).strip()
            if not native_id or not label:
                continue
            candidate_group = str(candidate.get("type") or "person") == "group"
            candidate_id = stable_id(
                "group" if candidate_group else "person", "authority", native_id
            )
            add(
                _identity(
                    candidate_id,
                    label,
                    group=candidate_group,
                    native_id=native_id,
                )
            )
            candidate_rows.append(
                {
                    "identity_id": candidate_id,
                    "score": max(0.0, min(1.0, float(candidate.get("score") or 0.0))),
                    "features": {
                        "match_type": candidate.get("match_type"),
                        "evidence": candidate.get("evidence"),
                    },
                }
            )
        if candidate_rows:
            add(
                {
                    "id": stable_id("identity_hypothesis", mention_id, "authority-linker"),
                    "type": "identity_hypothesis",
                    "version": 1,
                    "mention_id": mention_id,
                    "candidates": candidate_rows,
                }
            )

    return {"schema_version": SCHEMA_VERSION, "objects": objects}


def validate_evidence_dataset(dataset: dict[str, Any]) -> None:
    """Apply operational, JSON Schema, and SHACL validation."""
    errors = validate_dataset(dataset)
    if errors:
        raise EvidencePipelineError("; ".join(errors))

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_errors = sorted(
        Draft202012Validator(schema).iter_errors(dataset),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        messages = [
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in schema_errors
        ]
        raise EvidencePipelineError("JSON Schema: " + "; ".join(messages))

    conforms, report = validate_graph(dataset_to_graph(dataset))
    if not conforms:
        raise EvidencePipelineError("SHACL validation failed: " + report)


def write_evidence_dataset(dataset: dict[str, Any], output_path: Path) -> Path:
    """Validate before atomically publishing a canonical JSON artifact."""
    validate_evidence_dataset(dataset)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(dataset))
    temporary.replace(output_path)
    return output_path
