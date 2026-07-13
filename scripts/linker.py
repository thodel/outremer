"""
linker.py
─────────
Layer-2 authority linking: fuzzy-match extracted person mentions against
the curated authority file (scripts/outremer_index.json).

Extracted from run_pipeline.py (Epic 10) so the evaluation harness can
re-link snapshots without importing the LLM stack, and so matching logic
lives in one place.

Matching (M10.1 + M10.2):
- ``normalise``: NFKD, strip accents, punctuation → space (hyphenated
  toponyms like "Saint-Gilles" split), lowercase, collapse whitespace.
- ``fold_particles``: additionally drops connective name particles
  (de/of/von/…), so "Godefroy de Bouillon" and "Godefroy of Bouillon"
  compare equal. Applied as a *second* comparison, never a replacement.
- ensemble score: max of token_sort_ratio on the plain forms,
  token_sort_ratio on the folded forms, and (for multi-token names)
  a damped token_set_ratio.

Thresholds are config-backed (M10.3): LINK_CANDIDATE_FLOOR / LINK_MEDIUM /
LINK_HIGH env vars, defaults 0.60 / 0.75 / 0.90.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from config import LINK_CANDIDATE_FLOOR, LINK_HIGH, LINK_MEDIUM

# Connective particles folded away for comparison. Deliberately short and
# Romance/Germanic only: Arabic structural elements (ibn, al-…) are
# name-bearing and must not be folded.
_PARTICLES = {"de", "of", "von", "du", "der", "des", "le", "la", "d"}


def normalise(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace, strip punctuation."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).lower().strip()


def fold_particles(norm: str) -> str:
    """Drop connective particles from an already-normalised name.

    Returns the input unchanged when folding would leave fewer than two
    tokens (a bare "Godefroy" must not match every Godefroy variant).
    """
    tokens = [t for t in norm.split() if t not in _PARTICLES]
    if len(tokens) < 2:
        return norm
    return " ".join(tokens)


def _fuzzy_score(a: str, b: str) -> float:
    """Ensemble fuzzy ratio on normalised names, 0.0–1.0 (M10.2)."""
    try:
        from rapidfuzz import fuzz
    except ImportError:
        # Fallback: simple token overlap
        set_a, set_b = set(a.split()), set(b.split())
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / max(len(set_a), len(set_b))

    score = fuzz.token_sort_ratio(a, b) / 100.0

    fa, fb = fold_particles(a), fold_particles(b)
    if (fa, fb) != (a, b):
        score = max(score, fuzz.token_sort_ratio(fa, fb) / 100.0)

    # token_set_ratio ignores word order/multiplicity — powerful for
    # reordered names, but on raw forms a shared particle ("of") plus a
    # shared given name inflates unrelated persons (measured: "Ralph of
    # Caen" vs "Ralph II of Fougères" → 0.79, overtaking the correct
    # candidate). Hence: folded forms only, ≥2 substantive tokens per
    # side, and damped below sort-order agreement.
    if len(fa.split()) >= 2 and len(fb.split()) >= 2:
        score = max(score, 0.90 * fuzz.token_set_ratio(fa, fb) / 100.0)

    return score


def _status(score: float) -> str:
    if score >= LINK_HIGH:
        return "high"
    if score >= LINK_MEDIUM:
        return "medium"
    if score >= LINK_CANDIDATE_FLOOR:
        return "low"
    return "no_match"


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

        for v in e.get("variants") or []:
            if isinstance(v, str) and v.strip():
                raw_variants.append(v.strip())

        norm_block = e.get("normalized") or {}
        if norm_block.get("preferred"):
            raw_variants.append(norm_block["preferred"])
        for v in norm_block.get("variants") or []:
            if isinstance(v, str) and v.strip():
                raw_variants.append(v.strip())

        name_block = e.get("name") or {}
        if isinstance(name_block, dict) and name_block.get("raw"):
            raw_variants.append(name_block["raw"])

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


def link_voyagers_to_outremer(
    persons: list[dict[str, Any]],
    authority_lookup: list[dict[str, Any]],
    top_k: int = 3,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    """
    Link extracted person mentions to Outremer authority entries using fuzzy matching.

    Returns one link object per person mention, each containing ranked candidates.
    """
    if min_score is None:
        min_score = LINK_CANDIDATE_FLOOR
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
                # Fuzzy ensemble
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
