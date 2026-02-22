#!/usr/bin/env python3
"""
process_staged.py
─────────────────
Move a staged upload into data/raw/ and run the pipeline on it.

Usage (from repo root):
    python scripts/process_staged.py <item_id>
    python scripts/process_staged.py --list        # show pending queue
    python scripts/process_staged.py --reject <id> # reject and delete

The item_id is the 8-char UUID prefix shown in the Discord notification.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO      = Path(__file__).parent.parent
STAGING   = REPO / "data" / "staging"
RAW       = REPO / "data" / "raw"
QUEUE     = STAGING / "queue.json"
VENV_PY   = REPO / ".venv" / "bin" / "python3"
PIPELINE  = REPO / "scripts" / "run_pipeline.py"


def load_queue() -> list:
    if not QUEUE.exists():
        return []
    return json.loads(QUEUE.read_text())


def save_queue(q: list) -> None:
    QUEUE.write_text(json.dumps(q, indent=2, ensure_ascii=False))


def find_item(q: list, item_id: str) -> dict | None:
    return next((x for x in q if x["id"] == item_id), None)


def cmd_list() -> None:
    q = load_queue()
    pending = [x for x in q if x.get("status") == "pending"]
    if not pending:
        print("No pending uploads.")
        return
    print(f"{'ID':<10} {'Uploaded':<20} {'Original filename':<40} {'Size':>8}  Title")
    print("-" * 100)
    for x in pending:
        kb = x["size_bytes"] // 1024
        title = (x.get("title") or "—")[:35]
        ts    = x["uploaded_at"][:16].replace("T", " ")
        print(f"{x['id']:<10} {ts:<20} {x['original']:<40} {kb:>6} KB  {title}")


def cmd_reject(item_id: str) -> None:
    q = load_queue()
    item = find_item(q, item_id)
    if not item:
        print(f"No item with id '{item_id}' found.")
        sys.exit(1)

    staged = STAGING / item["filename"]
    if staged.exists():
        staged.unlink()
        print(f"Deleted staged file: {item['filename']}")

    item["status"] = "rejected"
    item["rejected_at"] = datetime.utcnow().isoformat()
    save_queue(q)
    print(f"Item {item_id} marked as rejected.")


def cmd_process(item_id: str) -> None:
    q = load_queue()
    item = find_item(q, item_id)
    if not item:
        print(f"No item with id '{item_id}' found.")
        sys.exit(1)

    if item.get("status") != "pending":
        print(f"Item is not pending (status: {item.get('status')}). Nothing to do.")
        sys.exit(0)

    staged = STAGING / item["filename"]
    if not staged.exists():
        print(f"Staged file not found: {staged}")
        sys.exit(1)

    # Move to data/raw/
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / item["original"]
    # If a file with that name already exists, prefix with timestamp
    if dest.exists():
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_")
        dest = RAW / (ts + item["original"])

    shutil.move(str(staged), str(dest))
    print(f"Moved to data/raw/: {dest.name}")

    # Update queue
    item["status"]       = "processed"
    item["processed_at"] = datetime.utcnow().isoformat()
    item["raw_file"]     = dest.name
    save_queue(q)

    # Determine Python executable
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable

    # Run pipeline
    api_key         = os.environ.get("GOOGLE_API_KEY", "")
    mistral_api_key = os.environ.get("MISTRAL_API_KEY", "***REDACTED***")
    env = os.environ.copy()
    if api_key:
        env["GOOGLE_API_KEY"] = api_key
    env["MISTRAL_API_KEY"] = mistral_api_key

    print(f"\nRunning pipeline (GOOGLE_API_KEY {'set' if api_key else 'NOT SET — fallback mode'})…")
    result = subprocess.run(
        [py, str(PIPELINE), "--input-dir", str(RAW), "--genai-metadata"],
        cwd=str(REPO),
        env=env,
    )
    if result.returncode != 0:
        print("Pipeline failed.")
        sys.exit(result.returncode)

    print("\nPipeline complete.")

    # Commit
    git_add = subprocess.run(
        ["git", "add", "site/data/", "site/bib/", "bib/", "site/index.json",
         "data/raw/", "data/staging/queue.json"],
        cwd=str(REPO),
    )
    if git_add.returncode != 0:
        print("git add failed.")
        sys.exit(1)

    msg = f"chore: process upload '{dest.name}' via process_staged.py"
    subprocess.run(["git", "commit", "-m", msg], cwd=str(REPO), check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=str(REPO), check=True)

    print(f"\nDone. Results pushed to GitHub. Explorer will update after Pages deploy.")
    print(f"Source file: data/raw/{dest.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Manage staged Outremer uploads.")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("item_id", nargs="?", help="Process the item with this ID")
    grp.add_argument("--list",   action="store_true", help="List pending uploads")
    grp.add_argument("--reject", metavar="ID",        help="Reject and delete a staged item")
    args = ap.parse_args()

    if args.list:
        cmd_list()
    elif args.reject:
        cmd_reject(args.reject)
    else:
        cmd_process(args.item_id)


if __name__ == "__main__":
    main()
