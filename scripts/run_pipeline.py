#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from extract_persons_google import extract_persons_and_metadata

def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "doc"

def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()

def load_outremer_index(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"entities": []}
    return json.loads(path.read_text(encoding="utf-8"))

def simple_link_voyagers_to_outremer(persons: List[Dict[str, Any]], outremer: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Placeholder linking:
    - Exact/substring match of person name against any entity aliases in outremer index.
    Replace with your real linker when ready.
    """
    entities = outremer.get("entities", [])
    links: List[Dict[str, Any]] = []

    for p in persons:
        pname = (p.get("name") or "").strip()
        if not pname:
            continue

        for e in entities:
            aliases = [e.get("name", "")] + (e.get("aliases") or [])
            aliases = [a for a in aliases if isinstance(a, str)]
            hit = any(a.lower() in pname.lower() or pname.lower() in a.lower() for a in aliases if a)
            if hit:
                links.append({
                    "person": pname,
                    "outremer_id": e.get("id"),
                    "outremer_name": e.get("name"),
                    "type": e.get("type", "unknown"),
                    "confidence": 0.65,
                    "evidence": "name/alias match"
                })
    return links

def process_file(
    in_path: Path,
    out_dir: Path,
    bib_dir: Path,
    outremer_index: Dict[str, Any],
    use_genai_metadata: bool,
) -> Tuple[Path, Path]:
    text = in_path.read_text(encoding="utf-8", errors="replace")
    base = slugify(in_path.stem)
    doc_hash = sha256_text(text)[:12]
    doc_id = f"{base}-{doc_hash}"

    result = extract_persons_and_metadata(text, use_genai_metadata=use_genai_metadata)
    persons = result.get("persons", [])
    metadata = result.get("metadata", {})
    bibtex = result.get("bibtex", "")

    # Add linking (Voyagers -> Outremer)
    links = simple_link_voyagers_to_outremer(persons, outremer_index)

    payload: Dict[str, Any] = {
        "doc_id": doc_id,
        "source_file": str(in_path.as_posix()),
        "metadata": metadata,
        "persons": persons,
        "links": links,
        "text_sha256": sha256_text(text),
    }

    out_path = out_dir / f"{doc_id}.json"
    bib_path = bib_dir / f"{doc_id}.bib"

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    bib_path.write_text(bibtex or "", encoding="utf-8")

    return out_path, bib_path

def build_site_index(out_dir: Path, site_dir: Path) -> None:
    files = sorted(out_dir.glob("*.json"))
    index = {
        "generated_from": "GitHub Actions pipeline",
        "count": len(files),
        "documents": [f.name for f in files],
    }
    (site_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default="data/raw", help="Folder with .txt files")
    ap.add_argument("--output-dir", default="output")
    ap.add_argument("--bib-dir", default="bib")
    ap.add_argument("--site-dir", default="site")
    ap.add_argument("--outremer-index", default="scripts/outremer_index.json")
    ap.add_argument("--genai-metadata", action="store_true", help="Enable GenAI metadata extraction")
    args = ap.parse_args()

    in_dir = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    bib_dir = Path(args.bib_dir)
    site_dir = Path(args.site_dir)
    outremer_path = Path(args.outremer_index)

    out_dir.mkdir(parents=True, exist_ok=True)
    bib_dir.mkdir(parents=True, exist_ok=True)
    site_dir.mkdir(parents=True, exist_ok=True)

    outremer_index = load_outremer_index(outremer_path)

    inputs = sorted(in_dir.rglob("*.txt"))
    if not inputs:
        print(f"No .txt files found in {in_dir}")
    else:
        for p in inputs:
            out_path, bib_path = process_file(
                p, out_dir, bib_dir, outremer_index, use_genai_metadata=args.genai_metadata
            )
            print(f"Wrote {out_path} and {bib_path}")

    build_site_index(out_dir, site_dir)
    print(f"Wrote {site_dir / 'index.json'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
