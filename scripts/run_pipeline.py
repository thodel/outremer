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

GPUSTACK_BASE_URL (from .env.gpustack) activates GPUStack extraction;
falls back to heuristic NER if absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import EXTRACTION_MODEL, OCR_ENGINE
from extract_persons_google import extract_persons_and_metadata

from scripts.llm_client import generate as _llm_generate

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────

def _write_run_report(
    *,
    run_at: str,
    docs_total: int,
    docs_ok: int,
    docs_failed: int,
    total_persons: int,
    extraction_model: str,
    ocr_engine: str,
    failures: list[dict],
) -> None:
    """Write run report JSON to data/staging/run_report.json."""
    report = {
        "run_at": run_at,
        "docs_total": docs_total,
        "docs_ok": docs_ok,
        "docs_failed": docs_failed,
        "total_persons": total_persons,
        "llm_provider": "gpustack",
        "extraction_model": extraction_model,
        "ocr_engine": ocr_engine,
        "failures": failures,
    }
    staging_dir = Path("data/staging")
    staging_dir.mkdir(parents=True, exist_ok=True)
    report_path = staging_dir / "run_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    logger.info("Run report written to %s", report_path)



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
    """Extract text from PDF. Falls back to Mistral OCR for image-only PDFs."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "pypdf is required to read PDFs. Install with: pip install pypdf"
        ) from exc
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()

    # Heuristic: if we got very little text, it's probably a scanned/image PDF
    if len(text) < 200:
        logger.info("Low text yield from pypdf (%d chars) — trying OCR (engine=%s)…", len(text), OCR_ENGINE)
        ocr_text = _ocr_image(path)
        if ocr_text:
            logger.info("Mistral OCR returned %d chars.", len(ocr_text))
            return ocr_text
        logger.warning("OCR also failed; proceeding with minimal text.")

    return text


def _ocr_image(path: Path) -> str:
    """
    OCR dispatcher — tries engines in priority order per OCR_ENGINE setting.

    # Priority chain:
      qwen3-vl → GPUStack Qwen3 VL 30B (primary, GPU)
               → GPUStack MiniMax-M2.7
               → Mistral (legacy fallback)
      gpustack → GPUStack MiniMax-M2.7
               → Mistral
      mistral  → Mistral only (legacy)
    """
    # qwen3-vl (default): Qwen3 VL 30B primary → MiniMax fallback → Mistral final
    result = _qwen3vl_ocr(path)
    if result:
        return result
    logger.info("Qwen3 VL OCR empty — trying MiniMax-M2.7.")
    result = _minimax_ocr(path)
    if result:
        return result
    logger.info("MiniMax OCR also empty — trying Mistral as last resort.")
    return _minimax_ocr(path)



def _qwen3vl_ocr(path: Path) -> str:
    """GPUStack Qwen3 VL 30B for primary document OCR."""
    import base64

    from config import QWEN3_VL_MODEL

    b64 = base64.b64encode(path.read_bytes()).decode()
    prompt = (
        "You are an OCR system. Given an image of a document page, transcribe ALL text "
        "exactly as it appears. Preserve line breaks, capitalization, and unusual characters. "
        "If the image is not a document page, respond with: [NOT_A_PAGE]\n\n"
        f"Image data: data:application/pdf;base64,{b64}"
    )
    try:
        text = _llm_generate(
            prompt,
            model=QWEN3_VL_MODEL,
            max_tokens=8192,
            temperature=0.0,
        )
        if text == "[NOT_A_PAGE]" or not text.strip():
            return ""
        logger.info("GPUStack OCR returned %d chars.", len(text))
        return text.strip()
    except Exception as exc:
        logger.error("GPUStack OCR error: %s", exc)
        return ""


def _minimax_ocr(path: Path) -> str:  # secondary GPUStack fallback
    """GPUStack MiniMax-M2.7 secondary → Mistral final fallback."""
    import base64
    api_key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not api_key:
        logger.warning("MISTRAL_API_KEY not set — cannot run OCR fallback.")
        return ""
    try:
        from mistralai import Mistral
    except ImportError:
        logger.warning("mistralai not installed — cannot run OCR fallback.")
        return ""

    try:
        client = Mistral(api_key=api_key)
        b64 = base64.b64encode(path.read_bytes()).decode()
        resp = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{b64}",
            },
        )
        pages = resp.pages if hasattr(resp, "pages") else []
        text = "\n\n".join(p.markdown for p in pages if p.markdown).strip()
        if text:
            logger.info("Mistral OCR returned %d chars.", len(text))
        return text
    except Exception as exc:
        logger.error("Mistral OCR error: %s", exc)
        return ""


def read_input(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".txt":
        return read_text_file(path)
    if ext == ".pdf":
        return read_pdf_file(path)
    raise ValueError(f"Unsupported input type: {path}")


def load_outremer_index(path: Path, *, require: bool = False) -> dict[str, Any]:
    if not path.exists():
        msg = f"Outremer index not found at {path}. Linking will be skipped."
        if require:
            raise FileNotFoundError(msg)
        logger.warning(msg)
        return {"entities": [], "persons": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Outremer index is not valid JSON: {path}") from exc
    # The index uses "persons" key (authority file format)
    return data


def _load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not parse JSON file %s: %s", path, exc)
        return default


def _canonical_person_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").replace("\n", " ").strip())


def _canonical_review_decision(decision: Any) -> str:
    d = str(decision or "").strip().lower()
    if d.startswith("reject"):
        return "reject"
    if d in {"not_a_person", "wrong_era"}:
        return "reject"
    if d.startswith("accept"):
        return "accept"
    return d


def _load_human_review_decisions(path: Path) -> list[dict[str, Any]]:
    """
    Supports:
    - server-style list: [{doc_id, person, decision, ...}, ...]
    - explorer export map: {"doc::person::id": {decision, ...}, ...}
    """
    raw = _load_json_file(path, default=[])
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        out: list[dict[str, Any]] = []
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            if not isinstance(key, str):
                continue
            parts = key.split("::")
            person = parts[1] if len(parts) >= 2 else ""
            out.append(
                {
                    "doc_id": parts[0] if len(parts) >= 1 else None,
                    "person": person,
                    "outremer_id": parts[2] if len(parts) >= 3 else None,
                    "decision": value.get("decision"),
                    "comment": value.get("comment"),
                    "submitted_at": value.get("ts"),
                }
            )
        return out
    return []


def sync_feedback_from_human_review(
    feedback_path: Path,
    decisions_path: Path,
    *,
    min_reject_votes: int = 2,
    min_accept_votes: int = 1,
) -> dict[str, int]:
    """
    Sync blocked/allow lists from review decisions:
    - Reject/not_a_person/wrong_era votes push a name toward blocked_terms.
    - Accept votes push a name toward allow_terms and can un-block.
    """
    decisions = _load_human_review_decisions(decisions_path)
    if not decisions:
        return {"processed": 0, "blocked_added": 0, "allowed_added": 0, "blocked_removed": 0}

    feedback = _load_json_file(
        feedback_path,
        default={"schema_version": 1, "blocked_terms": [], "allow_terms": [], "auto_flagged": {}},
    )
    if not isinstance(feedback, dict):
        feedback = {"schema_version": 1, "blocked_terms": [], "allow_terms": [], "auto_flagged": {}}

    blocked_terms = [str(x).strip() for x in (feedback.get("blocked_terms") or []) if str(x).strip()]
    allow_terms = [str(x).strip() for x in (feedback.get("allow_terms") or []) if str(x).strip()]

    name_by_norm: dict[str, str] = {}
    reject_counts: Counter[str] = Counter()
    accept_counts: Counter[str] = Counter()

    reject_labels = {"reject", "not_a_person", "wrong_era"}
    for d in decisions:
        decision = _canonical_review_decision(d.get("decision"))
        person = _canonical_person_name(str(d.get("person") or ""))
        if not person:
            continue
        norm = normalise(person)
        if not norm:
            continue
        name_by_norm[norm] = person
        if decision in reject_labels:
            reject_counts[norm] += 1
        elif decision == "accept":
            accept_counts[norm] += 1

    blocked_norms = {normalise(x): x for x in blocked_terms}
    allow_norms = {normalise(x): x for x in allow_terms}

    blocked_added = 0
    allowed_added = 0
    blocked_removed = 0

    for norm, name in name_by_norm.items():
        rejects = reject_counts[norm]
        accepts = accept_counts[norm]

        should_allow = accepts >= min_accept_votes and accepts >= rejects
        should_block = rejects >= min_reject_votes and rejects > accepts

        if should_allow:
            if norm in blocked_norms:
                del blocked_norms[norm]
                blocked_removed += 1
            if norm not in allow_norms:
                allow_norms[norm] = name
                allowed_added += 1
        elif should_block:
            if norm not in blocked_norms:
                blocked_norms[norm] = name
                blocked_added += 1
            if norm in allow_norms:
                del allow_norms[norm]

    feedback["blocked_terms"] = sorted(blocked_norms.values(), key=lambda x: x.lower())
    feedback["allow_terms"] = sorted(allow_norms.values(), key=lambda x: x.lower())
    feedback["human_review"] = {
        "source_file": str(decisions_path),
        "processed_decisions": len(decisions),
        "min_reject_votes": min_reject_votes,
        "min_accept_votes": min_accept_votes,
    }
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "processed": len(decisions),
        "blocked_added": blocked_added,
        "allowed_added": allowed_added,
        "blocked_removed": blocked_removed,
    }


# ──────────────────────────────────────────────
# Authority index preprocessing
# ──────────────────────────────────────────────

def build_authority_lookup(outremer: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Pre-process the authority index into a flat list of
    { authority_id, preferred_label, type, all_norms: [str] }
    ready for fuzzy matching.
    """
    # Support both old ("entities") and new ("persons") top-level keys
    entries = outremer.get("persons") or outremer.get("entities") or []
    lookup: list[dict[str, Any]] = []

    for e in entries:
        auth_id = (e.get("authority_id") or "").strip()
        label = (e.get("preferred_label") or e.get("name") or "").strip()
        etype = e.get("type", "person")

        # Collect all name variants to match against
        raw_variants: list[str] = [label]

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
        all_norms: list[str] = []
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
    persons: list[dict[str, Any]],
    authority_lookup: list[dict[str, Any]],
    top_k: int = 3,
    min_score: float = 0.60,
) -> list[dict[str, Any]]:
    """
    Link extracted person mentions to Outremer authority entries using fuzzy matching.

    Returns one link object per person mention, each containing ranked candidates.
    """
    links: list[dict[str, Any]] = []

    for p in persons:
        pname = (p.get("name") or "").strip()
        if not pname:
            continue
        pnorm = normalise(pname)
        p_tokens = pnorm.split()

        # Score every authority entry
        scored: list[tuple[float, str, dict[str, Any]]] = []  # (score, match_type, entry)
        for entry in authority_lookup:
            best_score = 0.0
            best_match_type = "fuzzy"

            for variant_norm in entry["all_norms"]:
                v_tokens = variant_norm.split()
                # Exact match
                if pnorm == variant_norm:
                    best_score = 1.0
                    best_match_type = "exact"
                    break
                # Token containment (reduces false positives from naive substrings)
                elif len(p_tokens) >= 2 and all(t in v_tokens for t in p_tokens):
                    sub_score = len(p_tokens) / max(len(v_tokens), 1)
                    if sub_score > best_score:
                        best_score = sub_score
                        best_match_type = "token_subset"
                elif len(v_tokens) >= 2 and all(t in p_tokens for t in v_tokens):
                    sub_score = len(v_tokens) / max(len(p_tokens), 1)
                    if sub_score > best_score:
                        best_score = sub_score
                        best_match_type = "token_subset"
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
    seen: dict[tuple[str, str], int] = {}  # key → index in links
    deduped: list[dict[str, Any]] = []
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
    authority_lookup: list[dict[str, Any]],
    use_genai_metadata: bool,
    language: str | None = None,
    entity_feedback_path: Path | None = None,
) -> tuple[Path, Path, Path]:
    logger.info("Processing %s …", in_path.name)
    text = read_input(in_path)

    base = slugify(in_path.stem)
    doc_hash = sha256_text(text)[:12]
    doc_id = f"{base}-{doc_hash}"

    result = extract_persons_and_metadata(
        text,
        use_genai_metadata=use_genai_metadata,
        language=language,
        feedback_path=str(entity_feedback_path) if entity_feedback_path else None,
        source_id=str(in_path.as_posix()),
    )
    persons: list[dict[str, Any]] = result.get("persons") or []
    metadata: dict[str, Any] = result.get("metadata") or {}
    bibtex: str = result.get("bibtex") or ""

    links = link_voyagers_to_outremer(persons, authority_lookup)

    payload: dict[str, Any] = {
        "doc_id": doc_id,
        "source_file": str(in_path.as_posix()),
        "input_type": in_path.suffix.lower().lstrip("."),
        "metadata": metadata,
        "persons": persons,
        "links": links,
        "text_sha256": sha256_text(text),
        "extraction_mode": "gemini" if os.environ.get("GOOGLE_API_KEY") else "fallback",
        "language_hint": language,
        "quality": result.get("quality") or {},
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
        sum(1 for _l in links if _l["status"] == "high"),
        sum(1 for _l in links if _l["status"] == "medium"),
        sum(1 for _l in links if _l["status"] == "low"),
        sum(1 for _l in links if _l["status"] == "no_match"),
    )
    return json_path, bib_path_repo, bib_path_site


def build_site_index(site_data_dir: Path, site_dir: Path) -> None:
    _EXCLUDE = {"wikidata_matches.json", "authority.json"}
    files = sorted(f for f in site_data_dir.glob("*.json") if f.name not in _EXCLUDE)
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
    ap.add_argument("--file", action="append", dest="files", metavar="FILE", help="Process specific file(s) only (can be repeated)")
    ap.add_argument("--site-dir", default="site", help="Static site folder")
    ap.add_argument("--bib-dir", default="bib", help="Repo-level BibTeX output folder")
    ap.add_argument("--outremer-index", default="scripts/outremer_index.json")
    ap.add_argument(
        "--require-outremer-index",
        action="store_true",
        help="Fail if the Outremer index file is missing",
    )
    ap.add_argument("--genai-metadata", action="store_true", help="Extract metadata + BibTeX via GenAI")
    ap.add_argument("--language", default=None, help="ISO 639 language hint (la, fro, ar, el, de, en…)")
    ap.add_argument(
        "--entity-feedback-path",
        default="data/entity_feedback.json",
        help="JSON store for problematic entities used as Gemini negative memory",
    )
    ap.add_argument(
        "--review-decisions-path",
        default=None,
        help="Optional JSON with human review decisions to sync into blocked/allow terms",
    )
    ap.add_argument(
        "--review-min-reject-votes",
        type=int,
        default=2,
        help="Min reject/not_a_person/wrong_era votes required to add a term to blocked_terms",
    )
    ap.add_argument(
        "--review-min-accept-votes",
        type=int,
        default=1,
        help="Min accept votes required to add a term to allow_terms",
    )
    args = ap.parse_args()

    in_dir = Path(args.input_dir)
    site_dir = Path(args.site_dir)
    bib_dir = Path(args.bib_dir)
    outremer_path = Path(args.outremer_index)
    entity_feedback_path = Path(args.entity_feedback_path) if args.entity_feedback_path else None
    review_decisions_path = Path(args.review_decisions_path) if args.review_decisions_path else None

    site_data_dir = site_dir / "data"
    site_bib_dir = site_dir / "bib"

    for d in (site_dir, site_data_dir, site_bib_dir, bib_dir):
        d.mkdir(parents=True, exist_ok=True)

    try:
        outremer_index = load_outremer_index(
            outremer_path, require=args.require_outremer_index
        )
    except Exception as exc:
        logger.error("%s", exc)
        return 1
    authority_lookup = build_authority_lookup(outremer_index)
    logger.info("Loaded %d authority entries.", len(authority_lookup))

    if entity_feedback_path and review_decisions_path:
        stats = sync_feedback_from_human_review(
            entity_feedback_path,
            review_decisions_path,
            min_reject_votes=max(1, args.review_min_reject_votes),
            min_accept_votes=max(1, args.review_min_accept_votes),
        )
        logger.info(
            "Synced review feedback: %d decisions, +%d blocked, +%d allowed, -%d blocked",
            stats["processed"],
            stats["blocked_added"],
            stats["allowed_added"],
            stats["blocked_removed"],
        )

    # Specific files or all files in directory
    if args.files:
        inputs: list[Path] = [Path(f) for f in args.files]
        logger.info("Processing %d specified file(s).", len(inputs))
    else:
        inputs = sorted(set(list(in_dir.rglob("*.txt")) + list(in_dir.rglob("*.pdf"))))

    errors: list[tuple[Path, Exception]] = []
    if not inputs:
        logger.warning("No .txt or .pdf files found in %s", in_dir)
    else:
        for p in inputs:
            try:
                json_path, bib_repo, bib_site = process_file(
                    p,
                    site_data_dir=site_data_dir,
                    bib_dir=bib_dir,
                    site_bib_dir=site_bib_dir,
                    authority_lookup=authority_lookup,
                    use_genai_metadata=args.genai_metadata,
                    language=args.language,
                    entity_feedback_path=entity_feedback_path,
                )
                print(f"Wrote {json_path}")
                print(f"Wrote {bib_repo}")
                print(f"Wrote {bib_site}")
            except Exception as exc:
                errors.append((p, exc))
                logger.error("Failed processing %s: %s", p, exc)

    build_site_index(site_data_dir=site_data_dir, site_dir=site_dir)
    print(f"Wrote {site_dir / 'index.json'}")

    # Keep authority file in sync for the People Lookup page
    import shutil
    authority_src = Path(__file__).parent / "outremer_index.json"
    authority_dst = site_data_dir / "authority.json"
    if authority_src.exists():
        shutil.copy2(authority_src, authority_dst)
        print(f"Copied authority file → {authority_dst}")

    # Optional: Wikidata reconciliation for no_match persons
    wikidata_script = Path(__file__).parent / "wikidata_reconcile.py"
    if wikidata_script.exists():
        logger.info("Running Wikidata reconciliation…")
        import subprocess
        subprocess.run(
            [sys.executable, str(wikidata_script), "--site-dir", str(site_dir)],
            cwd=str(Path(__file__).parent.parent),
        )

    _write_run_report(
        run_at=datetime.now(timezone.utc).isoformat(),
        docs_total=len(inputs),
        docs_ok=len(inputs) - len(errors),
        docs_failed=len(errors),
        total_persons=0,
        extraction_model=EXTRACTION_MODEL,
        ocr_engine=OCR_ENGINE,
        failures=[{"file": str(p), "error": str(e)} for p, e in errors],
    )

    if errors:
        logger.error("Completed with %d error(s).", len(errors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
