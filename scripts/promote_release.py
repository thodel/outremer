#!/usr/bin/env python3
"""Atomically promote or roll back a verified Outremer release directory."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class PromotionError(RuntimeError):
    pass


def resolve_release(release_root: Path, release: Path) -> Path:
    root = release_root.resolve()
    releases = (root / "releases").resolve()
    candidate = release.resolve()
    if candidate.parent != releases or not candidate.is_dir():
        raise PromotionError("release must be an existing direct child of RELEASE_ROOT/releases")
    if not (candidate / "release-manifest.json").is_file():
        raise PromotionError("release has no release-manifest.json")
    manifest = json.loads((candidate / "release-manifest.json").read_text())
    if manifest.get("profile") != "tei-production" or manifest.get("source", {}).get("dirty"):
        raise PromotionError("release manifest is not a clean tei-production manifest")
    if manifest.get("source", {}).get("commit") != candidate.name:
        raise PromotionError("release directory name must equal the manifested commit")
    return candidate


def current_target(release_root: Path) -> str | None:
    current = release_root / "current"
    return str(current.resolve()) if current.is_symlink() and current.exists() else None


def switch(release_root: Path, release: Path, history: Path, action: str) -> dict:
    release_root = release_root.resolve()
    candidate = resolve_release(release_root, release)
    previous = current_target(release_root)
    release_root.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".current-", dir=release_root)
    os.close(fd)
    temporary = Path(temporary_name)
    temporary.unlink()
    temporary.symlink_to(candidate)
    os.replace(temporary, release_root / "current")
    event = {
        "action": action,
        "at": datetime.now(timezone.utc).isoformat(),
        "from": previous,
        "to": str(candidate),
        "manifest_sha256": __import__("hashlib").sha256(
            (candidate / "release-manifest.json").read_bytes()
        ).hexdigest(),
    }
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return event


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["promote", "rollback"])
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(switch(args.release_root, args.release, args.history, args.action)))
    except (PromotionError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
