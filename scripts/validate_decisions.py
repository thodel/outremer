"""
Decision file validation and multi-reviewer merge logic.

Schema for decisions.json (list format):
  {
    "doc_id":     string,   # required — identifies the source document
    "person":     string,   # required — the person name string
    "decision":   string,   # required — one of VALID_DECISIONS
    "client_id":  string,   # optional — anonymous reviewer ID
    "submitted_at": string, # optional — ISO 8601 timestamp
    "comment":    string,   # optional
    "outremer_id": string,  # optional — specific authority ID targeted
  }

Valid decisions: reject | accept | not_a_person | wrong_era | is_group

Multi-reviewer merge rules:
  - Per (doc_id, person, id) key, decisions from different client_ids are tracked separately
  - A conflict arises when the same key has both accept and reject decisions from different clients
  - Voting thresholds (min_accept_votes, min_reject_votes) apply to counts across all clients
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VALID_DECISIONS: frozenset[str] = frozenset(
    {"reject", "accept", "not_a_person", "wrong_era", "is_group"}
)
REJECT_DECISIONS: frozenset[str] = frozenset({"reject", "not_a_person", "wrong_era", "is_group"})


@dataclass
class DecisionRecord:
    """A single validated decision."""

    doc_id: str
    person: str
    decision: str
    client_id: str = "anonymous"
    submitted_at: str | None = None
    comment: str | None = None
    outremer_id: str | None = None


@dataclass
class ValidationError:
    """A single schema violation."""

    entry_index: int
    field: str
    message: str


@dataclass
class ConflictRecord:
    """A name that received conflicting decisions from different reviewers."""

    doc_id: str
    person: str
    id: str
    accepts: list[str]  # client_ids that accepted
    rejects: list[str]  # client_ids that rejected
    final_decision: str  # resolved by vote threshold


@dataclass
class ValidationResult:
    """Result of validating and parsing a decisions file."""

    records: list[DecisionRecord] = field(default_factory=list)
    errors: list[ValidationError] = field(default_factory=list)
    conflicts: list[ConflictRecord] = field(default_factory=list)
    total_entries: int = 0


def _normalise_key(*parts: str) -> str:
    """Build a normalised lookup key from components."""
    return "::".join(p.strip().lower() for p in parts)


def _is_valid_iso(ts: str) -> bool:
    try:
        from datetime import datetime

        datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


def _validate_record(raw: dict[str, Any], index: int) -> tuple[DecisionRecord | None, list[ValidationError]]:
    """Validate a single raw decision dict, returning a record or errors."""
    errors: list[ValidationError] = []

    if not isinstance(raw, dict):
        errors.append(ValidationError(index, "", "entry is not a dict"))
        return None, errors

    # Required fields
    doc_id = str(raw.get("doc_id") or "").strip()
    if not doc_id:
        errors.append(ValidationError(index, "doc_id", "doc_id is required and must be a non-empty string"))

    person = str(raw.get("person") or "").strip()
    if not person:
        errors.append(ValidationError(index, "person", "person is required and must be a non-empty string"))

    decision = str(raw.get("decision") or "").strip()
    if not decision:
        errors.append(ValidationError(index, "decision", "decision is required"))
    elif decision not in VALID_DECISIONS:
        errors.append(
            ValidationError(
                index,
                "decision",
                f"decision must be one of {sorted(VALID_DECISIONS)}, got '{decision}'",
            )
        )

    client_id = str(raw.get("client_id") or "anonymous").strip()
    if client_id.startswith("anon-"):
        # Sanitise generated anonymous IDs
        client_id = re.sub(r"[^a-z0-9-]", "", client_id.lower())
        if len(client_id) < 8:
            client_id = "anonymous"

    submitted_at = raw.get("submitted_at")
    if submitted_at is not None:
        submitted_at = str(submitted_at).strip()
        if submitted_at and not _is_valid_iso(submitted_at):
            errors.append(
                ValidationError(index, "submitted_at", f"submitted_at is not a valid ISO 8601 timestamp: {submitted_at}")
            )
            submitted_at = None

    comment = raw.get("comment")
    if comment is not None:
        comment = str(comment).strip() or None

    outremer_id = raw.get("outremer_id")
    if outremer_id is not None:
        outremer_id = str(outremer_id).strip() or None

    if errors:
        return None, errors

    return (
        DecisionRecord(
            doc_id=doc_id,
            person=person,
            decision=decision,
            client_id=client_id,
            submitted_at=submitted_at or None,
            comment=comment,
            outremer_id=outremer_id,
        ),
        [],
    )


def _detect_conflicts(
    records: list[DecisionRecord],
    *,
    min_reject_votes: int = 2,
    min_accept_votes: int = 1,
) -> list[ConflictRecord]:
    """
    Detect conflicting decisions across reviewers.

    A conflict exists when the same (doc_id, person, id) receives both
    accept and reject decisions from DIFFERENT client_ids.
    """
    # Index by normalised key → {client_id: decision}
    key_clients: dict[str, dict[str, str]] = {}
    key_info: dict[str, tuple] = {}

    for r in records:
        key = _normalise_key(r.doc_id, r.person, r.outremer_id or "")
        if key not in key_clients:
            key_clients[key] = {}
            key_info[key] = (r.doc_id, r.person, r.outremer_id or "")
        key_clients[key][r.client_id] = r.decision

    conflicts: list[ConflictRecord] = []
    for key, client_decisions in key_clients.items():
        accepts = [cid for cid, d in client_decisions.items() if d == "accept"]
        rejects = [cid for cid, d in client_decisions.items() if d in REJECT_DECISIONS]

        if not accepts or not rejects:
            continue  # No conflict

        doc_id, person, out_id = key_info[key]

        # Resolve final decision by vote count
        final = "accept"
        if len(rejects) >= min_reject_votes and len(rejects) > len(accepts):
            final = "reject"
        elif len(accepts) >= min_accept_votes and len(accepts) >= len(rejects):
            final = "accept"
        else:
            final = "conflict_unresolved"

        conflicts.append(
            ConflictRecord(
                doc_id=doc_id,
                person=person,
                id=out_id or "(any)",
                accepts=accepts,
                rejects=rejects,
                final_decision=final,
            )
        )

    return conflicts


def validate_decisions_file(path: Path) -> ValidationResult:
    """
    Load and validate a decisions JSON file.

    Supports two formats:
    - List: [{doc_id, person, decision, ...}, ...]
    - Map:  {"doc::person::id": {decision, ...}, ...}  (explorer export)
    """
    result = ValidationResult()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.errors.append(ValidationError(-1, "", f"invalid JSON: {exc}"))
        return result

    entries: list[dict[str, Any]]
    if isinstance(raw, list):
        entries = [x for x in raw if isinstance(x, dict)]
        result.total_entries = len(raw)
    elif isinstance(raw, dict):
        # Convert map format to list
        entries = []
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            parts = key.split("::")
            entries.append(
                {
                    "doc_id": parts[0] if len(parts) >= 1 else "",
                    "person": parts[1] if len(parts) >= 2 else "",
                    "decision": value.get("decision"),
                    "client_id": value.get("client_id"),
                    "submitted_at": value.get("ts"),
                    "comment": value.get("comment"),
                }
            )
        result.total_entries = len(raw)
    else:
        result.errors.append(ValidationError(-1, "", "root must be a JSON list or object, got " + type(raw).__name__))
        return result

    for i, entry in enumerate(entries):
        record, errors = _validate_record(entry, i)
        if errors:
            result.errors.extend(errors)
        elif record:
            result.records.append(record)

    result.conflicts = _detect_conflicts(result.records)
    return result


def format_validation_report(result: ValidationResult) -> str:
    """Build a human-readable validation report."""
    lines = []
    status = "✅" if not result.errors else "❌"
    lines.append(f"{status} Decisions file validation: {result.total_entries} entries, {len(result.records)} valid, {len(result.errors)} errors")

    if result.errors:
        lines.append("\nErrors:")
        seen: set[tuple] = set()
        for e in result.errors[:20]:
            k = (e.field, e.message)
            if k in seen:
                continue
            seen.add(k)
            loc = f"[index {e.entry_index}]" if e.entry_index >= 0 else "[file]"
            lines.append(f"  {loc} {e.field}: {e.message}" if e.field else f"  {loc} {e.message}")
        if len(result.errors) > 20:
            lines.append(f"  … and {len(result.errors) - 20} more errors")

    if result.conflicts:
        lines.append(f"\n⚠️  {len(result.conflicts)} conflict(s) detected:")
        for c in result.conflicts[:10]:
            lines.append(
                f"  {c.doc_id} :: {c.person} :: {c.id}: "
                f"accepts from {c.accepts}, rejects from {c.rejects} → {c.final_decision}"
            )
        if len(result.conflicts) > 10:
            lines.append(f"  … and {len(result.conflicts) - 10} more conflicts")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m scripts.validate_decisions <decisions.json>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"❌ File not found: {path}")
        sys.exit(1)

    result = validate_decisions_file(path)
    print(format_validation_report(result))
    sys.exit(1 if result.errors else 0)