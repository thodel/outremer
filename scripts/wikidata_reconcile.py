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
import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────

WD_SPARQL    = "https://query.wikidata.org/sparql"
WD_ENTITY    = "https://www.wikidata.org/wiki/{qid}"
WD_API_DELAY = 0.5    # seconds between requests (be polite to SPARQL endpoint)
USER_AGENT   = "outremer-poc/1.0 (https://github.com/thodel/outremer; tobias.hodel@unibe.ch)"

# Medieval Levant-relevant keywords for scoring
DESCRIPTION_WHITELIST_RE = re.compile(
    r"\b(crusad|knight|king|queen|count|bishop|pope|sultan|emir|patriarch|"
    r"noble|pilgrim|merchant|historian|chronicler|medieval|middle age|"
    r"latin east|outremer|templars?|hospitall?er|constable|duke|baron)\b",
    re.I,
)

# Cutoff: exclude persons who lived entirely after 1500 CE
MEDIEVAL_CUTOFF_YEAR = 1500


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).lower().strip()


def get_person_dates(qid: str) -> tuple[int | None, int | None]:
    """
    Fetch birth (P569) and death (P570) years for a Wikidata entity.
    Returns (birth_year, death_year) or (None, None) if unavailable.
    """
    sparql = f"""
SELECT ?birth ?death WHERE {{
  wd:{qid} wdt:P569 ?birth .
  OPTIONAL {{ wd:{qid} wdt:P570 ?death . }}
}}
"""
    params = urlencode({"query": sparql, "format": "json"})
    url = f"{WD_SPARQL}?{params}"
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/sparql-results+json",
    })
    try:
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        bindings = data.get("results", {}).get("bindings", [])
        if not bindings:
            return None, None
        
        birth_year = None
        death_year = None
        
        for b in bindings:
            birth_val = b.get("birth", {}).get("value", "")
            death_val = b.get("death", {}).get("value", "")
            
            # Parse ISO dates (e.g., "1145-01-01T00:00:00Z")
            if birth_val and not birth_year:
                match = re.match(r'(\d{4})', birth_val)
                if match:
                    birth_year = int(match.group(1))
            if death_val and not death_year:
                match = re.match(r'(\d{4})', death_val)
                if match:
                    death_year = int(match.group(1))
        
        return birth_year, death_year
    except Exception as e:
        logger.debug(f"Failed to fetch dates for {qid}: {e}")
        return None, None


def is_medieval_person(birth_year: int | None, death_year: int | None) -> bool:
    """
    Check if a person is medieval (not entirely post-1500).
    
    Returns True if:
    - No dates available (we can't filter, so include by default)
    - Birth year <= 1500
    - Death year <= 1500
    
    Returns False if:
    - Both birth AND death years are > 1500
    """
    if birth_year is None and death_year is None:
        return True  # No dates, include by default
    
    if birth_year and birth_year <= MEDIEVAL_CUTOFF_YEAR:
        return True
    
    if death_year and death_year <= MEDIEVAL_CUTOFF_YEAR:
        return True
    
    # Both dates are after 1500
    if birth_year and death_year and birth_year > MEDIEVAL_CUTOFF_YEAR:
        return False
    
    return True


def wd_search_humans(name: str, lang: str = "en", limit: int = 5) -> list[dict[str, Any]]:
    """
    Query Wikidata SPARQL endpoint for persons matching `name` that are
    instance-of human (P31=Q5). Returns list of dicts with keys:
    id, label, description.
    Places, geographical features, and other non-human entities are excluded.
    We cast a wide inner search (20 candidates) and then apply P31=Q5 filter,
    so that lower-ranked persons aren't lost to non-human items near the top.
    """
    safe_name = name.replace('"', '').replace('\\', '')
    sparql = f"""
SELECT ?item ?itemLabel ?itemDescription WHERE {{
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:endpoint "www.wikidata.org" ;
                    wikibase:api "EntitySearch" ;
                    mwapi:search "{safe_name}" ;
                    mwapi:language "{lang}" ;
                    mwapi:limit "20" .
    ?item wikibase:apiOutputItem mwapi:item .
  }}
  ?item wdt:P31 wd:Q5 .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{lang},en" . }}
}}
LIMIT {limit}
"""
    params = urlencode({"query": sparql, "format": "json"})
    url = f"{WD_SPARQL}?{params}"
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/sparql-results+json",
    })
    with urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    bindings = data.get("results", {}).get("bindings", [])
    results = []
    for b in bindings:
        qid   = b["item"]["value"].rsplit("/", 1)[-1]
        label = b.get("itemLabel", {}).get("value", "")
        desc  = b.get("itemDescription", {}).get("value", "")
        # Skip if label is just the QID (no useful label)
        if label == qid:
            continue
        results.append({"id": qid, "label": label, "description": desc})
    return results


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


# ── Logging ─────────────────────────────────────────────────────────────────
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def reconcile_person(name: str, limit: int = 3) -> list[dict[str, Any]]:
    """Return top Wikidata human candidates for a person name (P31=Q5 only).
    
    Filters out post-medieval persons (born after 1500) when dates are available.
    """
    try:
        results = wd_search_humans(name, limit=limit + 5)
    except Exception as e:
        print(f"  Wikidata error for '{name}': {e}")
        return []

    candidates = []
    filtered_count = 0
    
    for r in results:
        qid = r.get("id", "")
        if not qid.startswith("Q"):
            continue
        
        # Check birth/death dates to filter post-medieval persons
        birth_year, death_year = get_person_dates(qid)
        if not is_medieval_person(birth_year, death_year):
            logger.debug(f"  Filtered post-medieval: {r.get('label', qid)} (b.{birth_year}, d.{death_year})")
            filtered_count += 1
            continue
        
        sc = score_candidate(name, r)
        candidate = {
            "qid":         qid,
            "label":       r.get("label", ""),
            "description": r.get("description", ""),
            "url":         WD_ENTITY.format(qid=qid),
            "score":       round(sc, 3),
            "birth_year":  birth_year,
            "death_year":  death_year,
        }
        candidates.append(candidate)

    # Sort by score desc; keep top `limit`
    candidates.sort(key=lambda x: x["score"], reverse=True)
    
    if filtered_count > 0:
        logger.info(f"  {name}: filtered {filtered_count} post-medieval candidates")
    
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
