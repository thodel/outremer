"""
M21.2 (#126): the reranker as a veto on the fuzzy linker, not as a ranker.

Measured first (2026-10-11, every corpus mention relinked, top-5 fuzzy
candidates from floor 0.60, jina-reranker-v2-base-multilingual on GPUStack):

* Ranking: of the 21 mentions whose correct record exists, the fuzzy top was
  already correct for all 21; the reranker's top was correct for 19 (record
  label + variants as document) or 20 (plus the QID's description and dates).
  It reorders nothing for the better and twice moves Munro's "Godfrey" from
  Godfrey of Bouillon to Godfrey III of Louvain.
* Veto: on the 120 mentions for which no correct record exists — the noise
  the medium band is made of — the reranker's relevance for the fuzzy top is
  low (median 0.10, p90 0.20, max 0.30), while a correct top scores 0.18–0.79
  with enriched documents. Below 0.25 the top is almost never right.

So the reranker does not reorder; it answers one question per mention — "does
any recorded person fit this mention in its context at all?" — and when the
answer is no, the link becomes no_match and its candidates stay visible
with their relevance, for review. Enabled by OUTREMER_CAPABILITY_RERANKER;
OFF produces byte-identical links to the fuzzy linker (M21.1's rule).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "jina-reranker-v2-base-multilingual"


def enabled() -> bool:
    return os.environ.get("OUTREMER_CAPABILITY_RERANKER", "false").casefold() in {"1", "true", "yes", "on"}


def settings() -> dict[str, Any]:
    from config import GPUSTACK_API_KEY, GPUSTACK_BASE_URL, WIKIDATA_SNAPSHOT

    return {
        "base_url": GPUSTACK_BASE_URL.rstrip("/"),
        "api_key": GPUSTACK_API_KEY,
        "model": os.environ.get("GPUSTACK_MODEL_RERANKER") or DEFAULT_MODEL,
        "min_relevance": float(os.environ.get("RERANK_MIN_RELEVANCE", "0.25")),
        "context_chars": int(os.environ.get("RERANK_CONTEXT_CHARS", "300")),
        "timeout": float(os.environ.get("RERANK_TIMEOUT", "30")),
        "snapshot": WIKIDATA_SNAPSHOT,
    }


class _SnapshotFacts:
    """Description and dates of a QID from the pre-1500 snapshot, if configured."""

    def __init__(self, path: str | None):
        self._con = None
        if path and Path(path).exists():
            try:
                self._con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            except sqlite3.Error as exc:  # unusable file: documents stay bare
                logger.warning("reranker: snapshot %s unusable (%s)", path, exc)

    def facts(self, qid: str | None) -> str:
        if not qid or self._con is None:
            return ""
        row = self._con.execute(
            "SELECT description, birth_year, death_year FROM persons WHERE qid=?", (qid,)
        ).fetchone()
        if not row:
            return ""
        desc, b, d = row
        bits = [desc] if desc else []
        if b or d:
            bits.append(f"lived {b or '?'}–{d or '?'}")
        return ". ".join(bits)


def record_text(record: dict[str, Any], facts: str = "") -> str:
    """What the reranker reads about a record: name, what the record knows, forms."""
    name = record.get("name") or {}
    bits = [record.get("preferred_label", "")]
    if facts:
        bits.append(facts)
    for key in ("toponym", "epithet", "regnal"):
        if name.get(key):
            bits.append(f"{key}: {name[key]}")
    forms = [v for v in (record.get("variants") or []) if len(str(v).split()) >= 2][:6]
    if forms:
        bits.append("also " + "; ".join(forms))
    return ". ".join(b for b in bits if b)


def rerank(query: str, documents: list[str], conf: dict[str, Any]) -> list[float]:
    """Relevance per document (same order), from GPUStack's /rerank."""
    body = json.dumps({"model": conf["model"], "query": query, "documents": documents,
                       "top_n": len(documents)}).encode("utf-8")
    req = urllib.request.Request(
        conf["base_url"] + "/rerank", data=body,
        headers={"Authorization": f"Bearer {conf['api_key']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=conf["timeout"]) as resp:
        results = json.loads(resp.read().decode("utf-8"))["results"]
    scores = [0.0] * len(documents)
    for item in results:
        scores[item["index"]] = float(item["relevance_score"])
    return scores


def apply_veto(links: list[dict[str, Any]], persons: list[dict[str, Any]],
               records: dict[str, dict[str, Any]], *, conf: dict[str, Any] | None = None,
               rerank_fn=rerank) -> dict[str, Any]:
    """Veto links whose best candidate does not fit the mention in context.

    Mutates *links* in place; returns a summary for the document's provenance.
    A failing reranker leaves the links as the fuzzy linker made them and says
    so in the summary — a veto is never worth a failed document.
    """
    conf = conf or settings()
    facts = _SnapshotFacts(conf.get("snapshot"))
    context = {p.get("name"): (p.get("context") or "") for p in persons}
    summary: dict[str, Any] = {"model": conf["model"], "min_relevance": conf["min_relevance"],
                               "checked": 0, "vetoed": 0, "errors": 0}
    for link in links:
        cands = link.get("candidates") or []
        if not cands:
            continue
        query = f"{link['person']}. {context.get(link['person'], '')[:conf['context_chars']]}".strip()
        docs = []
        for c in cands:
            rec = records.get(c["outremer_id"]) or {}
            qid = (rec.get("identifiers") or {}).get("wikidata_qid")
            docs.append(record_text(rec, facts.facts(qid)) or c.get("outremer_name", ""))
        try:
            scores = rerank_fn(query, docs, conf)
        except Exception as exc:  # unreachable backend, refused, timed out
            summary["errors"] += 1
            link["rerank"] = {"model": conf["model"], "error": str(exc)[:200]}
            logger.warning("reranker: %s left as fuzzy-linked (%s)", link["person"], exc)
            continue
        for c, s in zip(cands, scores):
            c["relevance"] = round(s, 4)
        top_rel = scores[0] if scores else 0.0
        veto = top_rel < conf["min_relevance"]
        link["rerank"] = {"model": conf["model"], "top_relevance": round(top_rel, 4),
                          "min_relevance": conf["min_relevance"], "veto": veto}
        summary["checked"] += 1
        if veto:
            summary["vetoed"] += 1
            link["top_candidate"] = None
            link["confidence"] = 0.0
            link["status"] = "no_match"
    return summary
