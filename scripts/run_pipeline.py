#!/usr/bin/env python3
"""
run_pipeline.py
───────────────
Main pipeline: read source texts → extract persons → link to Outremer KG → write JSON + BibTeX.

Usage
─────
    python scripts/run_pipeline.py [--input-dir data/raw] [--site-dir site] \
        [--bib-dir bib] [--outremer-index scripts/outremer_index.json] \
        [--genai-metadata]

GOOGLE_API_KEY env var activates Gemini extraction; falls back to heuristics if absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from extract_persons_google import extract_persons_and_metadata

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────

def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "doc"


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def normalise(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace, strip punctuation."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).lower().strip()


# ──────────────────────────────────────────────
# I/O helpers
# ──────────────────────────────────────────────

def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_pdf_file(path: Path) -> str:
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
        return {"entities": [], "persons": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    # The index uses "persons" key (authority file format)
    return data


# ──────────────────────────────────────────────
# Authority index preprocessing
# ──────────────────────────────────────────────

def build_authority_lookup(outremer: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pre-process the authority index into a flat list of
    { authority_id, preferred_label, type, all_norms: [str] }
    ready for fuzzy matching.
    """
    # Support both old ("entities") and new ("persons") top-level keys
    entries = outremer.get("persons") or outremer.get("entities") or []
    lookup: List[Dict[str, Any]] = []

    for e in entries:
        auth_id = (e.get("authority_id") or "").strip()
        label = (e.get("preferred_label") or e.get("name") or "").strip()
        etype = e.get("type", "person")

        # Collect all name variants to match against
        raw_variants: List[str] = [label]

        # From variants list
        for v in e.get("variants") or []:
            if isinstance(v, str) and v.strip():
                raw_variants.append(v.strip())

        # From normalized.variants
        norm_block = e.get("normalized") or {}
        if norm_block.get("preferred"):
            raw_variants.append(norm_block["preferred"])
        for v in norm_block.get("variants") or []:
            if isinstance(v, str) and v.strip():
                raw_variants.append(v.strip())

        # From name sub-object
        name_block = e.get("name") or {}
        if isinstance(name_block, dict):
            if name_block.get("raw"):
                raw_variants.append(name_block["raw"])

        # Deduplicate normalised forms
        seen: set = set()
        all_norms: List[str] = []
        for v in raw_variants:
            n = normalise(v)
            if n and n not in seen:
                seen.add(n)
                all_norms.append(n)

        if not auth_id or not label:
            continue

        lookup.append({
            "authority_id": auth_id,
            "preferred_label": label,
            "type": etype,
            "all_norms": all_norms,
        })

    return lookup


# ──────────────────────────────────────────────
# Fuzzy linker
# ──────────────────────────────────────────────

def _fuzzy_score(a: str, b: str) -> float:
    """Token-sort fuzzy ratio, 0.0–1.0."""
    try:
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a, b) / 100.0
    except ImportError:
        # Fallback: simple character overlap
        set_a, set_b = set(a.split()), set(b.split())
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / max(len(set_a), len(set_b))


def _status(score: float) -> str:
    if score >= 0.90:
        return "high"
    if score >= 0.75:
        return "medium"
    if score >= 0.60:
        return "low"
    return "no_match"


def link_voyagers_to_outremer(
    persons: List[Dict[str, Any]],
    authority_lookup: List[Dict[str, Any]],
    top_k: int = 3,
    min_score: float = 0.60,
) -> List[Dict[str, Any]]:
    """
    Link extracted person mentions to Outremer authority entries using fuzzy matching.

    Returns one link object per person mention, each containing ranked candidates.
    """
    links: List[Dict[str, Any]] = []

    for p in persons:
        pname = (p.get("name") or "").strip()
        if not pname:
            continue
        pnorm = normalise(pname)

        # Score every authority entry
        scored: List[Tuple[float, str, Dict[str, Any]]] = []  # (score, match_type, entry)
        for entry in authority_lookup:
            best_score = 0.0
            best_match_type = "fuzzy"

            for variant_norm in entry["all_norms"]:
                # Exact match
                if pnorm == variant_norm:
                    best_score = 1.0
                    best_match_type = "exact"
                    break
                # Substring containment
                elif pnorm in variant_norm or variant_norm in pnorm:
                    s = max(len(pnorm), len(variant_norm))
                    m = min(len(pnorm), len(variant_norm))
                    sub_score = m / s if s > 0 else 0.0
                    if sub_score > best_score:
                        best_score = sub_score
                        best_match_type = "alias"
                # Fuzzy
                else:
                    fs = _fuzzy_score(pnorm, variant_norm)
                    if fs > best_score:
                        best_score = fs
                        best_match_type = "fuzzy"

            if best_score >= min_score:
                scored.append((best_score, best_match_type, entry))

        # Sort descending by score, take top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        top_candidates = scored[:top_k]

        candidates = [
            {
                "outremer_id": entry["authority_id"],
                "outremer_name": entry["preferred_label"],
                "type": entry["type"],
                "score": round(score, 4),
                "match_type": match_type,
                "evidence": f"{match_type} match: '{pnorm}' ↔ '{entry['preferred_label']}'",
            }
            for score, match_type, entry in top_candidates
        ]

        top = candidates[0] if candidates else None
        confidence = top["score"] if top else 0.0
        status = _status(confidence) if top else "no_match"

        links.append({
            "person": pname,
            "person_group": p.get("group", False),
            "candidates": candidates,
            "top_candidate": top,
            "confidence": round(confidence, 4),
            "status": status,
        })

    # De-duplicate: if same (person, outremer_id) appears multiple times, keep highest score
    seen: Dict[Tuple[str, str], int] = {}  # key → index in links
    deduped: List[Dict[str, Any]] = []
    for link in links:
        top = link.get("top_candidate")
        key = (link["person"], top["outremer_id"] if top else "__none__")
        if key in seen:
            existing = deduped[seen[key]]
            if link["confidence"] > existing["confidence"]:
                deduped[seen[key]] = link
        else:
            seen[key] = len(deduped)
            deduped.append(link)

    return deduped


# ──────────────────────────────────────────────
# File processor
# ──────────────────────────────────────────────

def process_file(
    in_path: Path,
    site_data_dir: Path,
    bib_dir: Path,
    site_bib_dir: Path,
    authority_lookup: List[Dict[str, Any]],
    use_genai_metadata: bool,
) -> Tuple[Path, Path, Path]:
    logger.info("Processing %s …", in_path.name)
    text = read_input(in_path)

    base = slugify(in_path.stem)
    doc_hash = sha256_text(text)[:12]
    doc_id = f"{base}-{doc_hash}"

    result = extract_persons_and_metadata(text, use_genai_metadata=use_genai_metadata)
    persons: List[Dict[str, Any]] = result.get("persons") or []
    metadata: Dict[str, Any] = result.get("metadata") or {}
    bibtex: str = result.get("bibtex") or ""

    links = link_voyagers_to_outremer(persons, authority_lookup)

    payload: Dict[str, Any] = {
        "doc_id": doc_id,
        "source_file": str(in_path.as_posix()),
        "input_type": in_path.suffix.lower().lstrip("."),
        "metadata": metadata,
        "persons": persons,
        "links": links,
        "text_sha256": sha256_text(text),
        "extraction_mode": "gemini" if __import__("os").environ.get("GOOGLE_API_KEY") else "fallback",
    }

    json_path = site_data_dir / f"{doc_id}.json"
    bib_path_repo = bib_dir / f"{doc_id}.bib"
    bib_path_site = site_bib_dir / f"{doc_id}.bib"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    bib_path_repo.write_text(bibtex, encoding="utf-8")
    bib_path_site.write_text(bibtex, encoding="utf-8")

    logger.info(
        "  → %d persons, %d links (%d high / %d medium / %d low / %d no_match)",
        len(persons),
        len(links),
        sum(1 for l in links if l["status"] == "high"),
        sum(1 for l in links if l["status"] == "medium"),
        sum(1 for l in links if l["status"] == "low"),
        sum(1 for l in links if l["status"] == "no_match"),
    )
    return json_path, bib_path_repo, bib_path_site


def build_site_index(site_data_dir: Path, site_dir: Path) -> None:
    files = sorted(site_data_dir.glob("*.json"))
    index = {
        "generated_from": "run_pipeline.py",
        "count": len(files),
        "documents": [f.name for f in files],
    }
    (site_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Outremer NER + KG linking pipeline.")
    ap.add_argument("--input-dir", default="data/raw", help="Folder with .txt/.pdf files")
    ap.add_argument("--site-dir", default="site", help="Static site folder")
    ap.add_argument("--bib-dir", default="bib", help="Repo-level BibTeX output folder")
    ap.add_argument("--outremer-index", default="scripts/outremer_index.json")
    ap.add_argument("--genai-metadata", action="store_true", help="Extract metadata + BibTeX via GenAI")
    args = ap.parse_args()

    in_dir = Path(args.input_dir)
    site_dir = Path(args.site_dir)
    bib_dir = Path(args.bib_dir)
    outremer_path = Path(args.outremer_index)

    site_data_dir = site_dir / "data"
    site_bib_dir = site_dir / "bib"

    for d in (site_dir, site_data_dir, site_bib_dir, bib_dir):
        d.mkdir(parents=True, exist_ok=True)

    outremer_index = load_outremer_index(outremer_path)
    authority_lookup = build_authority_lookup(outremer_index)
    logger.info("Loaded %d authority entries.", len(authority_lookup))

    inputs: List[Path] = sorted(set(list(in_dir.rglob("*.txt")) + list(in_dir.rglob("*.pdf"))))

    if not inputs:
        logger.warning("No .txt or .pdf files found in %s", in_dir)
    else:
        for p in inputs:
            json_path, bib_repo, bib_site = process_file(
                p,
                site_data_dir=site_data_dir,
                bib_dir=bib_dir,
                site_bib_dir=site_bib_dir,
                authority_lookup=authority_lookup,
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
