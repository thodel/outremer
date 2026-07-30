import json
import os
from pathlib import Path

import pytest

from scripts.evidence_pipeline import (
    EvidencePipelineError,
    build_evidence_dataset,
    validate_evidence_dataset,
    write_evidence_dataset,
)


def source(tmp_path: Path) -> Path:
    path = tmp_path / "chronicle.txt"
    path.write_text("Baldwin went to Jerusalem.", encoding="utf-8")
    os.utime(path, (1_700_000_000, 1_700_000_000))
    return path


def dataset(tmp_path: Path):
    path = source(tmp_path)
    return build_evidence_dataset(
        in_path=path,
        doc_id="chronicle-a1b2c3",
        text_sha256="a" * 64,
        metadata={"title": "A Chronicle", "author": "Anonymous", "language": "en"},
        persons=[
            {
                "name": "Baldwin",
                "raw_mention": "Baldwin",
                "context": "Baldwin went to Jerusalem.",
                "source_offset": 0,
                "confidence": 0.87,
                "group": False,
            }
        ],
        links=[
            {
                "person": "Baldwin",
                "candidates": [
                    {
                        "outremer_id": "AUTH:CR1",
                        "outremer_name": "Baldwin I of Jerusalem",
                        "type": "person",
                        "score": 0.92,
                        "match_type": "variant",
                        "evidence": "preferred label",
                    }
                ],
            }
        ],
        extraction_engine={"provider": "gpustack", "model": "qwen"},
        language="en",
    )


def test_builds_deterministic_valid_evidence_dataset(tmp_path):
    first = dataset(tmp_path)
    second = dataset(tmp_path)
    assert first == second
    validate_evidence_dataset(first)
    types = {obj["type"] for obj in first["objects"]}
    assert {
        "source_work",
        "manifestation",
        "snapshot",
        "passage",
        "mention",
        "assertion",
        "person",
        "identity_hypothesis",
        "activity",
    } <= types


def test_writer_publishes_canonical_json_only_after_validation(tmp_path):
    data = dataset(tmp_path)
    output = tmp_path / "evidence" / "chronicle.evidence.json"
    write_evidence_dataset(data, output)
    assert json.loads(output.read_text(encoding="utf-8")) == data
    assert not output.with_suffix(".json.tmp").exists()


def test_validation_rejects_assertion_without_passage(tmp_path):
    data = dataset(tmp_path)
    assertion = next(obj for obj in data["objects"] if obj["type"] == "assertion")
    assertion["passage_ids"] = []
    with pytest.raises(EvidencePipelineError, match="evidence passage"):
        validate_evidence_dataset(data)
