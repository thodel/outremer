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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import EXTRACTION_MODEL, GPUSTACK_BASE_URL, OCR_ENGINE
from extract_persons_google import extract_persons_and_metadata
from linker import build_authority_lookup, link_voyagers_to_outremer, normalise
from llm_client import generate as _llm_generate
from validate_decisions import validate_decisions_file

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
    feedback_applied: dict[str, int] | None = None,
    llm_provider: str = "unknown",
    noise: dict[str, int] | None = None,
) -> None:
    """Write run report JSON to data/staging/run_report.json."""
    report = {
        "run_at": run_at,
        "docs_total": docs_total,
        "docs_ok": docs_ok,
        "docs_failed": docs_failed,
        "total_persons": total_persons,
        "llm_provider": llm_provider,
        "extraction_model": extraction_model,
        "ocr_engine": ocr_engine,
        "failures": failures,
    }
    if noise and noise.get("extracted_total"):
        report["noise"] = {
            **noise,
            "noise_share": round(noise["filtered"] / noise["extracted_total"], 4),
        }
    if feedback_applied:
        report["feedback_applied"] = {
            "source_file": str(feedback_applied.get("source_file", "")),
            "processed_decisions": feedback_applied.get("processed", 0),
            "blocked_added": feedback_applied.get("blocked_added", 0),
            "allowed_added": feedback_applied.get("allowed_added", 0),
            "blocked_removed": feedback_applied.get("blocked_removed", 0),
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
        # Provenance: which engine actually produced these persons
        "extraction_mode": (result.get("engine") or {}).get("provider", "unknown"),
        "extraction_engine": result.get("engine") or {},
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
    doc_stats = {
        "persons": len(persons),
        "noise": (result.get("quality") or {}).get("noise") or {},
    }
    return json_path, bib_path_repo, bib_path_site, doc_stats


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

    # ── Validate review decisions before processing ────────────────────────
    if review_decisions_path:
        from pathlib import Path as _P
        _dp = _P(review_decisions_path) if not isinstance(review_decisions_path, _P) else review_decisions_path
        logger.info("Validating decisions file: %s", _dp)
        vr = validate_decisions_file(_dp)
        if vr.errors:
            logger.error("Decision file has %d validation error(s):", len(vr.errors))
            for e in vr.errors[:10]:
                logger.error("  [%s] %s: %s",
                    f"index {e.entry_index}" if e.entry_index >= 0 else "file",
                    e.field or "", e.message)
            logger.error("Fix the errors above before re-running. Pipeline aborting.")
            return 1
        logger.info(
            "Validated: %d/%d decisions OK, %d conflict(s)",
            len(vr.records), vr.total_entries, len(vr.conflicts))
        if vr.conflicts:
            for c in vr.conflicts[:5]:
                logger.warning(
                    "  %s::%s::%s: accepts=%s rejects=%s → %s",
                    c.doc_id, c.person, c.id,
                    c.accepts, c.rejects, c.final_decision)

    feedback_stats: dict[str, int] | None = None
    if entity_feedback_path and review_decisions_path:
        feedback_stats = sync_feedback_from_human_review(
            entity_feedback_path,
            review_decisions_path,
            min_reject_votes=max(1, args.review_min_reject_votes),
            min_accept_votes=max(1, args.review_min_accept_votes),
        )
        logger.info(
            "Synced review feedback: %d decisions, +%d blocked, +%d allowed, -%d blocked",
            feedback_stats["processed"],
            feedback_stats["blocked_added"],
            feedback_stats["allowed_added"],
            feedback_stats["blocked_removed"],
        )

    # Specific files or all files in directory
    if args.files:
        inputs: list[Path] = [Path(f) for f in args.files]
        logger.info("Processing %d specified file(s).", len(inputs))
    else:
        inputs = sorted(set(list(in_dir.rglob("*.txt")) + list(in_dir.rglob("*.pdf"))))

    errors: list[tuple[Path, Exception]] = []
    total_persons = 0
    noise_agg = {"extracted_total": 0, "filtered": 0}
    if not inputs:
        logger.warning("No .txt or .pdf files found in %s", in_dir)
    else:
        for p in inputs:
            try:
                json_path, bib_repo, bib_site, doc_stats = process_file(
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
                total_persons += doc_stats["persons"]
                for k in noise_agg:
                    noise_agg[k] += (doc_stats.get("noise") or {}).get(k, 0)
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
        total_persons=total_persons,
        extraction_model=EXTRACTION_MODEL,
        ocr_engine=OCR_ENGINE,
        failures=[{"file": str(p), "error": str(e)} for p, e in errors],
        feedback_applied=feedback_stats,
        llm_provider="gpustack" if GPUSTACK_BASE_URL else "heuristic",
        noise=noise_agg,
    )

    if errors:
        logger.error("Completed with %d error(s).", len(errors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
