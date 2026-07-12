"""
evaluation/metrics.py

Extraction and linking metrics for the OUTREMER pipeline, so that
"did this prompt/model change help?" is a number, not a vibe.
Pattern adapted from agentic_historian's eval harness (CER/WER there;
person-mention P/R/F1 and adjudication agreement here).

Two evaluation modes:

1. **Full gold** (``extraction_prf``) — a scholar-curated list of every
   person mention that *should* be extracted from a document. Supports
   precision, recall, and F1. Expensive to produce; the long-term target.

2. **Adjudicated** (``linking_agreement``) — derived from Human-in-the-Loop
   decisions (data/decisions.json). Scholars accepted or rejected specific
   (mention, authority_id) candidate links. This measures how well the
   pipeline's link proposals agree with human judgement on the pairs that
   were reviewed. It says nothing about recall of unreviewed mentions —
   report it as agreement, never as overall accuracy.

All name matching is fuzzy (rapidfuzz token_sort_ratio) over normalised
strings, mirroring the linker's own matching so evaluation and production
agree on what counts as "the same name".
"""

from __future__ import annotations

import unicodedata

from rapidfuzz import fuzz

DEFAULT_FUZZY_THRESHOLD = 90.0


def normalise_name(s: str) -> str:
    """NFC-normalise, strip accents, casefold, collapse whitespace."""
    s = unicodedata.normalize("NFC", s or "")
    s = "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )
    return " ".join(s.casefold().split())


def _fuzzy_equal(a: str, b: str, threshold: float) -> bool:
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return fuzz.token_sort_ratio(na, nb) >= threshold


def extraction_prf(
    predicted: list[str],
    gold: list[str],
    *,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> dict:
    """
    Precision/recall/F1 of extracted person mentions against a full gold list.

    Matching is greedy one-to-one: each gold name may satisfy at most one
    prediction and vice versa, so duplicate predictions of the same person
    count as false positives rather than free true positives.
    """
    remaining_gold = list(gold)
    tp = 0
    false_positives: list[str] = []

    for pred in predicted:
        match_idx = None
        for i, g in enumerate(remaining_gold):
            if _fuzzy_equal(pred, g, fuzzy_threshold):
                match_idx = i
                break
        if match_idx is None:
            false_positives.append(pred)
        else:
            tp += 1
            remaining_gold.pop(match_idx)

    fp = len(false_positives)
    fn = len(remaining_gold)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positives": false_positives,
        "missed_gold": remaining_gold,
    }


def linking_agreement(
    predicted_links: list[dict],
    accepted: list[tuple[str, str]],
    rejected: list[tuple[str, str]],
    *,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> dict:
    """
    Agreement between the pipeline's top link candidates and human adjudication.

    Parameters
    ----------
    predicted_links:
        The ``links`` array from a site/data document JSON. Each entry has
        ``person`` and ``top_candidate`` (dict with ``authority_id`` or None).
    accepted / rejected:
        (person_name, authority_id) pairs a scholar accepted / rejected.

    Returns counts over the *reviewed* pairs only:

    - ``accept_hit``     — scholar accepted the pair, pipeline's top candidate agrees
    - ``accept_miss``    — scholar accepted, pipeline proposes something else / nothing
    - ``reject_avoided`` — scholar rejected, pipeline does NOT propose it (good)
    - ``reject_hit``     — scholar rejected, pipeline still proposes it (bad)
    """

    def top_auths(person: str) -> set[str]:
        """All authority ids proposed as top candidate for this person.

        The linker deduplicates on (person, top_id), so one person may have
        several link rows with different top candidates — agreement asks
        whether *any* of them proposes the adjudicated pair.
        """
        auths: set[str] = set()
        for link in predicted_links:
            if _fuzzy_equal(link.get("person", ""), person, fuzzy_threshold):
                top = link.get("top_candidate") or {}
                # production key is "outremer_id"; tolerate "authority_id"
                auth = top.get("outremer_id") or top.get("authority_id")
                if auth:
                    auths.add(auth)
        return auths

    accept_hit = accept_miss = 0
    for person, auth_id in accepted:
        if auth_id in top_auths(person):
            accept_hit += 1
        else:
            accept_miss += 1

    reject_hit = reject_avoided = 0
    for person, auth_id in rejected:
        if auth_id in top_auths(person):
            reject_hit += 1
        else:
            reject_avoided += 1

    reviewed = accept_hit + accept_miss + reject_hit + reject_avoided
    agreement = (
        (accept_hit + reject_avoided) / reviewed if reviewed else 0.0
    )
    return {
        "reviewed_pairs": reviewed,
        "accept_hit": accept_hit,
        "accept_miss": accept_miss,
        "reject_hit": reject_hit,
        "reject_avoided": reject_avoided,
        "agreement": round(agreement, 4),
    }


def format_report(doc_results: dict[str, dict]) -> str:
    """Render per-document results plus aggregate as an aligned text table."""
    lines: list[str] = []
    header = (
        f"{'document':<44} {'mode':<12} {'P':>6} {'R':>6} {'F1':>6} {'agree':>6}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for doc_id, res in sorted(doc_results.items()):
        ext = res.get("extraction") or {}
        link = res.get("linking") or {}
        lines.append(
            f"{doc_id[:44]:<44} {res.get('mode', '?'):<12}"
            f" {ext.get('precision', '—'):>6}"
            f" {ext.get('recall', '—'):>6}"
            f" {ext.get('f1', '—'):>6}"
            f" {link.get('agreement', '—'):>6}"
        )
    return "\n".join(lines)
