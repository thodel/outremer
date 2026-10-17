"""The corpus behind the MCP tools: published data, read-only, reloaded when it changes.

What is served and why only that (Epic 22, "Abgrenzung"): the nightly on tei
runs the pipeline, passes it through the provenance gate, and only then
commits ``site/data``. Those files are the publication; the work tree's
staging and the review database are not. This module reads the published
directory and nothing else, and it re-reads it when ``status.json`` changes,
which is once a night.

Name search goes through ``scripts/linker.py`` — the same code that links
mentions to records in production — so a search hit and a pipeline link mean
the same thing. The floor is lower here (a search lists candidates, a link
asserts one), and the reranker veto is never applied to a search.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import linker  # noqa: E402  (needs the path shim above)

EXPLORER_URL = "https://tei.dh.unibe.ch/outremer/"
#: Candidates a search lists; a link asserts at LINK_CANDIDATE_FLOOR (0.75).
SEARCH_FLOOR = 0.6


@dataclass
class Document:
    doc_id: str
    title: str
    author: str
    year: Any
    language: str
    persons: list[dict]
    links: list[dict]
    run_at: str
    linking_engine: dict
    extraction_engine: Any
    path: Path

    @property
    def citation(self) -> dict:
        return {"doc_id": self.doc_id, "title": self.title, "author": self.author, "year": self.year}


@dataclass
class Corpus:
    site_data: Path
    explorer_url: str = EXPLORER_URL
    records: dict[str, dict] = field(default_factory=dict)
    lookup: list[dict] = field(default_factory=list)
    documents: dict[str, Document] = field(default_factory=dict)
    status: dict = field(default_factory=dict)
    authority_meta: dict = field(default_factory=dict)
    _stamp: tuple = ()

    # ── loading ──────────────────────────────────────────────────────────────

    def _current_stamp(self) -> tuple:
        parts = []
        for name in ("status.json", "authority.json"):
            p = self.site_data / name
            parts.append(p.stat().st_mtime_ns if p.exists() else None)
        return tuple(parts)

    def load(self) -> Corpus:
        authority = json.loads((self.site_data / "authority.json").read_text(encoding="utf-8"))
        persons = authority.get("persons") or []
        self.authority_meta = {k: authority.get(k) for k in ("schema_version", "generated_at", "record_count")}
        self.records = {p["authority_id"]: p for p in persons if p.get("authority_id")}
        self.lookup = linker.build_authority_lookup({"persons": persons})
        status_path = self.site_data / "status.json"
        self.status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        docs: dict[str, Document] = {}
        for path in sorted(self.site_data.glob("*.json")):
            if path.name in {"authority.json", "status.json", "wikidata_matches.json", "index.json"}:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("doc_id") != path.stem or "persons" not in data:
                continue
            meta = data.get("metadata") or {}
            docs[path.stem] = Document(
                doc_id=path.stem, title=meta.get("title") or path.stem, author=meta.get("author") or "",
                year=meta.get("year"), language=meta.get("language") or "",
                persons=data.get("persons") or [], links=data.get("links") or [],
                run_at=data.get("run_at") or "", linking_engine=data.get("linking_engine") or {},
                extraction_engine=data.get("extraction_engine"), path=path,
            )
        self.documents = docs
        self._stamp = self._current_stamp()
        return self

    def maybe_reload(self) -> None:
        """Re-read after the nightly republished; a stat per call, nothing more."""
        if self._current_stamp() != self._stamp:
            self.load()

    # ── derived views ────────────────────────────────────────────────────────

    def mentions_of(self, authority_id: str) -> list[dict]:
        """Every published link whose top candidate is this record, with its mention."""
        out = []
        for doc in self.documents.values():
            by_name = {p.get("name"): p for p in doc.persons}
            for link in doc.links:
                top = link.get("top_candidate") or {}
                if top.get("outremer_id") != authority_id:
                    continue
                person = by_name.get(link.get("person")) or {}
                out.append(self._mention_hit(doc, person, link))
        return out

    def _mention_hit(self, doc: Document, person: dict, link: dict | None) -> dict:
        top = (link or {}).get("top_candidate") or {}
        return {
            "mention": person.get("name") or (link or {}).get("person"),
            "raw_mention": person.get("raw_mention"),
            "context": person.get("context"),
            "role": person.get("role"),
            "group": bool(person.get("group")),
            "document": doc.citation,
            "link": (
                {
                    "authority_id": top.get("outremer_id"),
                    "preferred_label": top.get("outremer_name"),
                    "status": link.get("status"),
                    "score": top.get("score"),
                    "relevance": top.get("relevance"),
                    "vetoed": bool((link.get("rerank") or {}).get("veto")),
                }
                if link else None
            ),
            "url": self.explorer_url,
            "data_url": f"{self.explorer_url}data/{doc.doc_id}.json",
        }

    def mention_counts(self) -> Counter:
        counts: Counter = Counter()
        for doc in self.documents.values():
            for link in doc.links:
                top = link.get("top_candidate") or {}
                if top.get("outremer_id"):
                    counts[top["outremer_id"]] += 1
        return counts

    # ── tools ────────────────────────────────────────────────────────────────

    def search_persons(self, query: str, limit: int = 10) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        links = linker.link_voyagers_to_outremer(
            [{"name": query}], self.lookup, top_k=max(1, min(limit, 50)),
            min_score=SEARCH_FLOOR, rerank=False,
        )
        counts = self.mention_counts()
        hits = []
        for link in links:
            for c in link.get("candidates") or []:
                rec = self.records.get(c["outremer_id"]) or {}
                ids = rec.get("identifiers") or {}
                hits.append({
                    "authority_id": c["outremer_id"],
                    "preferred_label": rec.get("preferred_label") or c.get("outremer_name"),
                    "score": c.get("score"),
                    "match_type": c.get("match_type"),
                    "evidence": c.get("evidence"),
                    "wikidata_qid": ids.get("wikidata_qid"),
                    "qid_status": (ids.get("wikidata_qid_provenance") or {}).get("status"),
                    "mentions": counts.get(c["outremer_id"], 0),
                    "url": self.explorer_url,
                    "data_url": f"{self.explorer_url}data/authority.json",
                })
        return hits[:limit]

    def get_person(self, authority_id: str) -> dict | None:
        rec = self.records.get((authority_id or "").strip())
        if rec is None:
            return None
        mentions = self.mentions_of(rec["authority_id"])
        per_doc: dict[str, int] = defaultdict(int)
        for m in mentions:
            per_doc[m["document"]["doc_id"]] += 1
        return {
            **rec,
            "mentions": {"total": len(mentions), "by_document": dict(per_doc), "examples": mentions[:5]},
            "url": self.explorer_url,
            "data_url": f"{self.explorer_url}data/authority.json",
        }

    def search_mentions(self, query: str, limit: int = 20, doc_id: str = "") -> list[dict]:
        q = linker.normalise(query or "")
        if not q:
            return []
        q_tokens = set(q.split())
        scored = []
        for doc in self.documents.values():
            if doc_id and doc.doc_id != doc_id:
                continue
            links_by_name = {lk.get("person"): lk for lk in doc.links}
            for person in doc.persons:
                name = person.get("name") or ""
                n = linker.normalise(name)
                raw = linker.normalise(person.get("raw_mention") or "")
                if q in n or q in raw:
                    score = 1.0 if q == n else 0.9
                elif q_tokens and q_tokens <= set(n.split()):
                    score = 0.8
                else:
                    score = linker._fuzzy_score(q, n)
                    if score < 0.75:
                        continue
                scored.append((score, self._mention_hit(doc, person, links_by_name.get(name))))
        scored.sort(key=lambda t: (-t[0], t[1]["mention"] or ""))
        return [dict(hit, score=round(score, 4)) for score, hit in scored[:limit]]

    def stats(self) -> dict:
        qid = Counter()
        for rec in self.records.values():
            ids = rec.get("identifiers") or {}
            qid[(ids.get("wikidata_qid_provenance") or {}).get("status") or
                ("asserted" if ids.get("wikidata_qid") else "none")] += 1
        docs = []
        bands: Counter = Counter()
        for doc in self.documents.values():
            doc_bands = Counter(lk.get("status") for lk in doc.links if lk.get("top_candidate"))
            bands.update(doc_bands)
            docs.append({**doc.citation, "language": doc.language, "mentions": len(doc.persons),
                         "links": dict(doc_bands), "run_at": doc.run_at,
                         "reranker": (doc.linking_engine or {}).get("reranker")})
        run = (self.status or {}).get("run") or {}
        return {
            "authority": {"records": len(self.records), "generated_at": self.authority_meta.get("generated_at"),
                          "wikidata_qid": dict(qid)},
            "documents": docs,
            "mentions": sum(len(d.persons) for d in self.documents.values()),
            "links_by_status": dict(bands),
            "last_run": {"run_at": run.get("run_at"), "gate": (self.status.get("gate") or {}).get("status"),
                         "extraction_model": run.get("extraction_model"), "models": run.get("models"),
                         "evaluation": (self.status.get("evaluation") or {}).get("segments")},
            "explorer": self.explorer_url,
        }
