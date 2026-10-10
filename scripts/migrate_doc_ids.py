#!/usr/bin/env python3
"""
Move every artefact from hash-bearing document ids to stable ones (#161).

    python scripts/migrate_doc_ids.py [--dry-run]

Old id:  <slug>-<sha256(text)[:12]>     e.g. hamblin-…-2001-f740c53422ef
New id:  <slug>                         e.g. hamblin-…-2001

For each source (the document's ``source_file``) the latest run becomes the
document under the new id — the same choice build_site_index makes — and
older states of the same source are removed. What is rewritten:

    site/data/<id>.json            renamed; doc_id rewritten, migrated_from kept
    site/bib, bib                  renamed; superseded states removed
    data/evidence, site/evidence   rebuilt from the migrated document (the
                                   evidence ids derive from doc_id)
    data/decisions.json            doc_id rewritten, migrated_from kept —
                                   append-only: the old value stays in the record
    evaluation/fixtures/<id>.json  renamed; doc_id rewritten
    site/data/wikidata_matches.json  keys rewritten; superseded states dropped
    data/doc_id_aliases.json       old → new, for the Explorer (#161)

Run once, commit the result, then ``python -m evaluation.build_fixture
--relink`` so fixtures carry the current document's predictions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

HASHED = re.compile(r"^(?P<slug>.+)-(?P<hash>[0-9a-f]{12})$")
NON_DOCUMENTS = {"authority", "wikidata_matches", "status", "index"}


def stable_id(doc_id: str) -> str:
    m = HASHED.match(doc_id)
    return m.group("slug") if m else doc_id


def plan(site_data: Path) -> dict[str, Any]:
    """Which file becomes which id; which files are superseded."""
    docs: dict[str, dict[str, Any]] = {}
    for path in sorted(site_data.glob("*.json")):
        if path.stem in NON_DOCUMENTS:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("doc_id") != path.stem or not data.get("source_file"):
            continue
        docs[path.stem] = {
            "new_id": stable_id(path.stem),
            "run_at": data.get("run_at") or "",
            "mtime": path.stat().st_mtime,
        }
    by_new: dict[str, list[str]] = {}
    for old, info in docs.items():
        by_new.setdefault(info["new_id"], []).append(old)
    current: dict[str, str] = {}      # new_id → old id that carries on
    superseded: list[str] = []
    for new_id, olds in by_new.items():
        olds.sort(key=lambda o: (docs[o]["run_at"], docs[o]["mtime"]), reverse=True)
        current[new_id] = olds[0]
        superseded.extend(olds[1:])
    aliases = {old: info["new_id"] for old, info in docs.items() if old != info["new_id"]}
    return {"current": current, "superseded": sorted(superseded), "aliases": aliases}


def _rename_json(src: Path, dst: Path, new_id: str, dry: bool) -> None:
    data = json.loads(src.read_text(encoding="utf-8"))
    if data.get("doc_id") != new_id:
        data["migrated_from"] = data.get("doc_id")
        data["doc_id"] = new_id
    print(f"  {src.name} → {dst.name}")
    if dry:
        return
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if src != dst:
        src.unlink()


def migrate(repo: Path = REPO_ROOT, *, dry: bool = False) -> dict[str, Any]:
    site = repo / "site"
    site_data = site / "data"
    p = plan(site_data)
    current, superseded, aliases = p["current"], p["superseded"], p["aliases"]
    if not aliases and not superseded:
        print("nothing to migrate: every document already has a stable id")
        return p

    print("documents:")
    for new_id, old in sorted(current.items()):
        if old != new_id:
            _rename_json(site_data / f"{old}.json", site_data / f"{new_id}.json", new_id, dry)
    for old in superseded:
        print(f"  {old}.json removed (superseded)")
        if not dry:
            (site_data / f"{old}.json").unlink(missing_ok=True)

    print("bib:")
    for bib_dir in (repo / "bib", site / "bib"):
        for new_id, old in sorted(current.items()):
            src, dst = bib_dir / f"{old}.bib", bib_dir / f"{new_id}.bib"
            if src.exists() and src != dst:
                print(f"  {src} → {dst.name}")
                if not dry:
                    src.rename(dst)
        for old in superseded:
            src = bib_dir / f"{old}.bib"
            if src.exists():
                print(f"  {src} removed (superseded)")
                if not dry:
                    src.unlink()

    print("evidence (rebuilt from the migrated documents):")
    for old_dir in (repo / "data" / "evidence", site / "evidence"):
        for name in list(current.values()) + superseded:
            stale = old_dir / f"{name}.evidence.json"
            if stale.exists() and name not in current:
                print(f"  {stale.name} removed (old id)")
                if not dry:
                    stale.unlink()
    if not dry:
        from evidence_pipeline import build_evidence_dataset, write_evidence_dataset

        for new_id in sorted(current):
            doc = json.loads((site_data / f"{new_id}.json").read_text(encoding="utf-8"))
            dataset = build_evidence_dataset(
                in_path=Path(doc["source_file"]),
                doc_id=new_id,
                text_sha256=doc["text_sha256"],
                metadata=doc.get("metadata") or {},
                persons=doc.get("persons") or [],
                links=doc.get("links") or [],
                extraction_engine=doc.get("extraction_engine") or {},
                language=doc.get("language_hint"),
            )
            for out_dir in (repo / "data" / "evidence", site / "evidence"):
                write_evidence_dataset(dataset, out_dir / f"{new_id}.evidence.json")
                print(f"  {out_dir / (new_id + '.evidence.json')}")

    print("decisions:")
    dec_path = repo / "data" / "decisions.json"
    decisions = json.loads(dec_path.read_text(encoding="utf-8"))
    moved = 0
    for d in decisions:
        old = d.get("doc_id")
        new_id = aliases.get(old)
        if new_id:
            d["migrated_from"] = old
            d["doc_id"] = new_id
            moved += 1
    print(f"  {moved} of {len(decisions)} decisions re-keyed")
    if not dry:
        dec_path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("fixtures:")
    fixtures = repo / "evaluation" / "fixtures"
    seen_new: set[str] = set()
    for old, new_id in sorted(aliases.items()):
        src = fixtures / f"{old}.json"
        if not src.exists():
            continue
        if new_id in seen_new:
            print(f"  {src.name} removed (a fixture for {new_id} already exists)")
            if not dry:
                src.unlink()
            continue
        _rename_json(src, fixtures / f"{new_id}.json", new_id, dry)
        seen_new.add(new_id)

    print("wikidata_matches:")
    wm_path = site_data / "wikidata_matches.json"
    if wm_path.exists():
        wm = json.loads(wm_path.read_text(encoding="utf-8"))
        out: dict[str, Any] = {}
        for key, value in wm.items():
            if key in superseded:
                print(f"  {key} dropped (superseded)")
            elif key in aliases:
                print(f"  {key} → {aliases[key]}")
                out[aliases[key]] = value
            elif key in NON_DOCUMENTS or key in current:
                out[key] = value
            else:
                print(f"  {key} dropped (not a current document)")
        if not dry:
            wm_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("aliases:")
    alias_path = repo / "data" / "doc_id_aliases.json"
    existing = {}
    if alias_path.exists():
        existing = (json.loads(alias_path.read_text(encoding="utf-8")) or {}).get("aliases") or {}
    merged = {**existing, **aliases}
    for old, new_id in sorted(aliases.items()):
        print(f"  {old} → {new_id}")
    if not dry:
        alias_path.write_text(json.dumps({"_comment": __doc__.split("\n")[1].strip(), "aliases": dict(sorted(merged.items()))},
                                         ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        from run_pipeline import build_site_index

        build_site_index(site_data, site)
        print("site/index.json rebuilt")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--repo", type=Path, default=REPO_ROOT)
    args = ap.parse_args(argv)
    migrate(args.repo, dry=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
