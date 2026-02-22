#!/usr/bin/env python3
"""
wikidata_reconcile.py
─────────────────────
For persons with status="no_match" in the pipeline output, query the Wikidata
Entity Search API and write candidate QIDs to site/data/wikidata_matches.json.

Usage (from repo root):
    python scripts/wikidata_reconcile.py [--site-dir site] [--limit 3]

The output file is fetched by the explorer UI to show Wikidata candidates for
unmatched persons alongside the authority-file candidates.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ── Config ─────────────────────────────────────────────────────────────────

WD_SEARCH    = "https://www.wikidata.org/w/api.php"
WD_ENTITY    = "https://www.wikidata.org/wiki/{qid}"
WD_API_DELAY = 0.35   # seconds between requests (be polite)
USER_AGENT   = "outremer-poc/1.0 (https://github.com/thodel/outremer; tobias.hodel@unibe.ch)"

# Medieval Levant-relevant instance types (Q5=human, Q215627=person)
# We also whitelist known Wikidata subclasses via description filtering
DESCRIPTION_WHITELIST_RE = re.compile(
    r"\b(crusad|knight|king|queen|count|bishop|pope|sultan|emir|patriarch|"
    r"noble|pilgrim|merchant|historian|chronicler|medieval|middle age|"
    r"latin east|outremer|templars?|hospitall?er|constable|duke|baron)\b",
    re.I,
)


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).lower().strip()


def wd_search(name: str, lang: str = "en", limit: int = 5) -> list[dict[str, Any]]:
    """Call Wikidata wbsearchentities API. Returns list of candidate dicts."""
    params = {
        "action":   "wbsearchentities",
        "search":   name,
        "language": lang,
        "type":     "item",
        "limit":    limit,
        "format":   "json",
    }
    url = f"{WD_SEARCH}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read()).get("search", [])


def score_candidate(name: str, cand: dict) -> float:
    """Heuristic relevance score 0.0–1.0 for a Wikidata candidate."""
    score = 0.0

    # Label similarity
    label = cand.get("label") or cand.get("display", {}).get("label", {}).get("value", "")
    if normalise(label) == normalise(name):
        score += 0.5
    elif normalise(name) in normalise(label) or normalise(label) in normalise(name):
        score += 0.3

    # Description relevance (medieval/crusades keywords)
    desc = cand.get("description", "")
    if DESCRIPTION_WHITELIST_RE.search(desc):
        score += 0.4

    # Penalize clearly modern entities
    if re.search(r"\b(born 1[5-9]\d\d|20th|21st century|politician|athlete|actor)\b", desc, re.I):
        score -= 0.5

    return max(0.0, min(1.0, score))


def reconcile_person(name: str, limit: int = 3) -> list[dict[str, Any]]:
    """Return top Wikidata candidates for a person name."""
    try:
        results = wd_search(name, limit=limit + 3)
    except Exception as e:
        print(f"  Wikidata error for '{name}': {e}")
        return []

    candidates = []
    for r in results:
        qid = r.get("id", "")
        if not qid.startswith("Q"):
            continue
        sc = score_candidate(name, r)
        candidates.append({
            "qid":         qid,
            "label":       r.get("label", ""),
            "description": r.get("description", ""),
            "url":         WD_ENTITY.format(qid=qid),
            "score":       round(sc, 3),
        })

    # Sort by score desc; keep top `limit`
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]


def run(site_dir: Path, limit: int) -> None:
    data_dir   = site_dir / "data"
    out_file   = site_dir / "data" / "wikidata_matches.json"

    if not data_dir.exists():
        print(f"No data dir at {data_dir}")
        return

    # Load existing matches to avoid re-querying
    existing: dict[str, Any] = {}
    if out_file.exists():
        try:
            existing = json.loads(out_file.read_text())
        except Exception:
            existing = {}

    doc_files = sorted(data_dir.glob("*.json"))
    doc_files  = [f for f in doc_files if f.name != "wikidata_matches.json"]

    total_queried = 0
    total_skipped = 0

    for doc_path in doc_files:
        doc = json.loads(doc_path.read_text())
        doc_id = doc.get("doc_id", doc_path.stem)

        if doc_id not in existing:
            existing[doc_id] = {}

        no_matches = [
            lnk for lnk in doc.get("links", [])
            if lnk.get("status") == "no_match"
        ]

        if not no_matches:
            continue

        print(f"\n[{doc_id}] {len(no_matches)} unmatched persons")

        for lnk in no_matches:
            person = lnk.get("person", "").strip()
            if not person or len(person) < 3:
                continue

            # Skip collectives
            if lnk.get("person_group"):
                continue

            key = normalise(person)

            if key in existing[doc_id]:
                total_skipped += 1
                continue   # already reconciled

            print(f"  Querying: {person}")
            candidates = reconcile_person(person, limit=limit)
            existing[doc_id][key] = {
                "person":     person,
                "candidates": candidates,
                "queried_at": __import__("datetime").datetime.utcnow().isoformat(),
            }
            total_queried += 1
            time.sleep(WD_API_DELAY)

    out_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    print(f"\nDone. Queried {total_queried} new persons, skipped {total_skipped} cached.")
    print(f"Output: {out_file}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Wikidata reconciliation for unmatched Outremer persons.")
    ap.add_argument("--site-dir", default="site")
    ap.add_argument("--limit", type=int, default=3, help="Max Wikidata candidates per person")
    args = ap.parse_args()
    run(Path(args.site_dir), args.limit)


if __name__ == "__main__":
    main()
