#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

# IMPORTANT:
# Your scripts/extract_persons_google.py MUST expose:
#   extract_persons_and_metadata(text: str, use_genai_metadata: bool = True) -> Dict[str, Any]
from extract_persons_google import extract_persons_and_metadata


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "doc"


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_pdf_file(path: Path) -> str:
    # pip install pypdf
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: List[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def read_input(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".txt":
        return read_text_file(path)
    if ext == ".pdf":
        return read_pdf_file(path)
    raise ValueError(f"Unsupported input type: {path}")


def load_outremer_index(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"entities": []}
    return json.loads(path.read_text(encoding="utf-8"))


def simple_link_voyagers_to_outremer(
    persons: List[Dict[str, Any]],
    outremer: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Placeholder linker:
      - exact/substring match of person name vs. outremer entity names/aliases
    Replace with your real linker later.
    """
    entities = outremer.get("entities", [])
    links: List[Dict[str, Any]] = []

    for p in persons:
        pname = (p.get("name") or "").strip()
        if not pname:
            continue

        pname_l = pname.lower()
        for e in entities:
            aliases = [e.get("name", "")] + (e.get("aliases") or [])
            aliases = [a for a in aliases if isinstance(a, str) and a.strip()]
            hit = any((a.lower() in pname_l) or (pname_l in a.lower()) for a in aliases)
            if hit:
                links.append(
                    {
                        "person": pname,
                        "outremer_id": e.get("id"),
                        "outremer_name": e.get("name"),
                        "type": e.get("type", "unknown"),
                        "confidence": 0.65,
                        "evidence": "name/alias match",
                    }
                )

    # de-dup
    seen = set()
    deduped = []
    for l in links:
        key = (l.get("person"), l.get("outremer_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(l)
    return deduped


def process_file(
    in_path: Path,
    site_data_dir: Path,
    bib_dir: Path,
    site_bib_dir: Path,
    outremer_index: Dict[str, Any],
    use_genai_metadata: bool,
) -> Tuple[Path, Path, Path]:
    text = read_input(in_path)

    base = slugify(in_path.stem)
    doc_hash = sha256_text(text)[:12]
    doc_id = f"{base}-{doc_hash}"

    result = extract_persons_and_metadata(text, use_genai_metadata=use_genai_metadata)
    persons = result.get("persons", []) or []
    metadata = result.get("metadata", {}) or {}
    bibtex = result.get("bibtex", "") or ""

    # Linking (Voyagers -> Outremer)
    links = simple_link_voyagers_to_outremer(persons, outremer_index)

    payload: Dict[str, Any] = {
        "doc_id": doc_id,
        "source_file": str(in_path.as_posix()),
        "input_type": in_path.suffix.lower().lstrip("."),
        "metadata": metadata,
        "persons": persons,
        "links": links,
        "text_sha256": sha256_text(text),
    }

    json_path = site_data_dir / f"{doc_id}.json"
    bib_path_repo = bib_dir / f"{doc_id}.bib"
    bib_path_site = site_bib_dir / f"{doc_id}.bib"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    bib_path_repo.write_text(bibtex, encoding="utf-8")
    bib_path_site.write_text(bibtex, encoding="utf-8")

    return json_path, bib_path_repo, bib_path_site


def build_site_index(site_data_dir: Path, site_dir: Path) -> None:
    files = sorted(site_data_dir.glob("*.json"))
    index = {
        "generated_from": "GitHub Actions pipeline",
        "count": len(files),
        "documents": [f.name for f in files],
    }
    (site_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default="data/raw", help="Folder with .txt/.pdf files")
    ap.add_argument("--site-dir", default="site", help="Static site folder")
    ap.add_argument("--bib-dir", default="bib", help="Repo-level BibTeX output folder")
    ap.add_argument("--outremer-index", default="scripts/outremer_index.json")
    ap.add_argument("--genai-metadata", action="store_true", help="Enable GenAI metadata extraction")
    args = ap.parse_args()

    in_dir = Path(args.input_dir)
    site_dir = Path(args.site_dir)
    bib_dir = Path(args.bib_dir)
    outremer_path = Path(args.outremer_index)

    site_data_dir = site_dir / "data"
    site_bib_dir = site_dir / "bib"

    site_dir.mkdir(parents=True, exist_ok=True)
    site_data_dir.mkdir(parents=True, exist_ok=True)
    site_bib_dir.mkdir(parents=True, exist_ok=True)
    bib_dir.mkdir(parents=True, exist_ok=True)

    outremer_index = load_outremer_index(outremer_path)

    inputs: List[Path] = []
    inputs += list(in_dir.rglob("*.txt"))
    inputs += list(in_dir.rglob("*.pdf"))
    inputs = sorted(set(inputs))

    if not inputs:
        print(f"No .txt or .pdf files found in {in_dir}")
    else:
        for p in inputs:
            json_path, bib_repo, bib_site = process_file(
                p,
                site_data_dir=site_data_dir,
                bib_dir=bib_dir,
                site_bib_dir=site_bib_dir,
                outremer_index=outremer_index,
                use_genai_metadata=args.genai_metadata,
            )
            print(f"Wrote {json_path}")
            print(f"Wrote {bib_repo}")
            print(f"Wrote {bib_site}")

    build_site_index(site_data_dir=site_data_dir, site_dir=site_dir)
    print(f"Wrote {site_dir / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
