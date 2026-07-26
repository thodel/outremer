#!/usr/bin/env python3
"""Rights-aware registry and publication gate for external data sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "data" / "sources" / "registry.json"
DEFAULT_QUARANTINE = ROOT / "data" / "quarantine" / "manifest.json"
DECISIONS = {"open-integrable", "permission-required", "reference-only", "excluded"}
REQUIRED = {
    "id", "name", "scope", "custodian", "contact", "source_type", "access",
    "licensing", "decision", "permitted_operations", "evidence_urls", "checked_at",
    "reviewer", "stable_identifiers", "formats", "update_cadence", "snapshot",
    "mapping_version", "sustainability", "provenance_granularity",
}


class SourcePolicyError(ValueError):
    """A source is missing, malformed, stale, or not permitted for an operation."""


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    sources = raw.get("sources", [])
    by_id = {source.get("id"): source for source in sources}
    if len(by_id) != len(sources) or None in by_id:
        raise SourcePolicyError("source ids must be present and unique")
    return by_id


def validate_registry(path: Path = DEFAULT_REGISTRY) -> list[str]:
    errors: list[str] = []
    try:
        sources = load_registry(path)
    except (OSError, json.JSONDecodeError, SourcePolicyError) as exc:
        return [str(exc)]
    for source_id, source in sources.items():
        missing = sorted(REQUIRED - source.keys())
        if missing:
            errors.append(f"{source_id}: missing {', '.join(missing)}")
        if source.get("decision") not in DECISIONS:
            errors.append(f"{source_id}: invalid decision {source.get('decision')!r}")
        if not source.get("evidence_urls"):
            errors.append(f"{source_id}: evidence_urls must not be empty")
        try:
            date.fromisoformat(source.get("checked_at", ""))
        except ValueError:
            errors.append(f"{source_id}: checked_at must be ISO date")
        access = source.get("access", {})
        for field in ("mechanism", "authentication", "robots", "rate_limit"):
            if not access.get(field):
                errors.append(f"{source_id}: access.{field} is required")
        licensing = source.get("licensing", {})
        for field in ("application_code", "data_content", "third_party_fields", "attribution"):
            if not licensing.get(field):
                errors.append(f"{source_id}: licensing.{field} is required")
    return errors


def require_operation(
    source_id: str,
    operation: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    written_permission: str | None = None,
) -> dict[str, Any]:
    source = load_registry(registry_path).get(source_id)
    if source is None:
        raise SourcePolicyError(f"unregistered source: {source_id}")
    permitted = operation in source["permitted_operations"]
    if source["decision"] == "open-integrable" and permitted:
        return source
    if written_permission and permitted:
        permission = Path(written_permission)
        if permission.is_file() and permission.stat().st_size:
            return source
    raise SourcePolicyError(
        f"{source_id} is {source['decision']}; operation {operation!r} is blocked"
    )


def quarantine_paths(path: Path = DEFAULT_QUARANTINE) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        item_path
        for item in raw.get("items", [])
        if not item.get("canonical_export") or not item.get("public_export")
        for item_path in item.get("paths", [])
    }


def snapshot_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def review_status(path: Path = DEFAULT_REGISTRY, *, today: date | None = None) -> dict:
    today = today or date.today()
    raw = json.loads(path.read_text(encoding="utf-8"))
    stale_after = int(raw["review_policy"]["stale_after_days"])
    report = {"checked_at": datetime.utcnow().isoformat() + "Z", "stale": []}
    for source in raw["sources"]:
        age = (today - date.fromisoformat(source["checked_at"])).days
        if age > stale_after:
            report["stale"].append({"id": source["id"], "age_days": age})
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "review"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        errors = validate_registry()
        if errors:
            print("\n".join(errors))
            return 1
        print(f"Registry valid: {len(load_registry())} sources")
        return 0
    report = review_status()
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
