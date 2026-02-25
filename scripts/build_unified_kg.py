#!/usr/bin/env python3
"""
build_unified_kg.py
───────────────────
Build a unified knowledge graph from:
1. Outremer authority file (126 persons)
2. Wikidata Peerage pre-1500 (~23,689 persons)
3. Extracted persons from pipeline output

Output: data/unified_kg.json
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def normalise(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace, remove punctuation."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).lower().strip()


def parse_iso_date(s: Optional[str]) -> Optional[str]:
    """Parse ISO date, return YYYY-MM-DD or YYYY."""
    if not s:
        return None
    # Handle Wikidata format: 1388-06-21T00:00:00Z
    s = s.replace("T00:00:00Z", "")
    return s


def load_outremer_authority(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load Outremer authority file, index by AUTH:ID."""
    data = json.loads(path.read_text())
    persons = {}
    for p in data.get("persons", []):
        auth_id = p.get("authority_id")
        if not auth_id:
            continue
        
        names = p.get("name", {})
        variants = p.get("variants", [])
        
        persons[auth_id] = {
            "id": auth_id,
            "preferred_label": p.get("preferred_label", ""),
            "identifiers": {"outremer_auth": auth_id},
            "names": {
                "preferred": p.get("preferred_label", ""),
                "variants": variants,
                "normalized": [normalise(v) for v in variants] + [normalise(p.get("preferred_label", ""))]
            },
            "bio": {},
            "roles": [],
            "relationships": [],
            "places": [],
            "provenance": {
                "sources": [{
                    "type": "authority",
                    "source_file": p.get("provenance", {}).get("source_files", ["unknown"])[0],
                    "confidence": 1.0
                }],
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            },
            "flags": {}
        }
        
        # Extract basic bio if available
        raw_name = names.get("raw", "")
        # Try to parse regnal numbers
        regnal_match = re.search(r'\b(I{1,3}|IV|IX|V?I{0,3})\b', raw_name)
        if regnal_match:
            pass  # Could extract regnal number
        
        # Extract toponym
        toponym = names.get("toponym")
        if toponym:
            persons[auth_id]["places"].append({
                "type": "title_seat",
                "label": toponym
            })
    
    return persons


def load_wikidata_peerage(dir_path: Path) -> Dict[str, Dict[str, Any]]:
    """Load Wikidata Peerage pre-1500 export, index by QID."""
    qids_file = dir_path / "qids.csv"
    data_pages_dir = dir_path / "data_pages"
    
    if not qids_file.exists():
        print(f"QIDs file not found: {qids_file}")
        return {}
    
    # Read all QIDs first
    qids = []
    with open(qids_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            item = row.get('item', '')
            if item.startswith('http://www.wikidata.org/entity/'):
                qid = item.rsplit('/', 1)[-1]
                qids.append(qid)
    
    print(f"Loaded {len(qids)} QIDs from peerage export")
    
    # Now load detailed data from CSV pages
    persons = {}
    csv_files = sorted(data_pages_dir.glob("*.csv"))
    
    for csv_file in csv_files:
        print(f"  Processing {csv_file.name}...")
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                item = row.get('item', '')
                if not item.startswith('http://www.wikidata.org/entity/'):
                    continue
                
                qid = item.rsplit('/', 1)[-1]
                item_label = row.get('itemLabel', '')
                
                if qid not in persons:
                    persons[qid] = {
                        "id": f"WIKIDATA:{qid}",
                        "preferred_label": item_label,
                        "identifiers": {"wikidata_qid": qid},
                        "names": {
                            "preferred": item_label,
                            "variants": [item_label],
                            "normalized": [normalise(item_label)]
                        },
                        "bio": {
                            "birth": None,
                            "death": None,
                            "floruit": None,
                            "gender": "unknown"
                        },
                        "roles": [],
                        "relationships": [],
                        "places": [],
                        "provenance": {
                            "sources": [{
                                "type": "wikidata",
                                "confidence": 1.0
                            }],
                            "created_at": datetime.utcnow().isoformat(),
                            "updated_at": datetime.utcnow().isoformat()
                        },
                        "flags": {}
                    }
                
                # Parse birth/death dates
                birth = row.get('birth')
                death = row.get('death')
                floruit = row.get('floruit')
                
                if birth and persons[qid]["bio"]["birth"] is None:
                    persons[qid]["bio"]["birth"] = {"date": parse_iso_date(birth)}
                if death and persons[qid]["bio"]["death"] is None:
                    persons[qid]["bio"]["death"] = {"date": parse_iso_date(death)}
                
                # Parse gender
                gender_val = row.get('valueLabel', '')
                prop = row.get('prop', '')
                if prop.endswith('/P21'):  # P21 = sex or gender
                    if 'male' in gender_val.lower():
                        persons[qid]["bio"]["gender"] = "m"
                    elif 'female' in gender_val.lower():
                        persons[qid]["bio"]["gender"] = "f"
                
                # Parse titles/offices (P39)
                if prop.endswith('/P39'):
                    persons[qid]["roles"].append({
                        "type": "title",
                        "label": row.get('valueLabel', ''),
                        "wikidata_ref": row.get('value', '').rsplit('/', 1)[-1] if row.get('value', '').startswith('http') else None,
                        "source": "wikidata"
                    })
                
                # Parse family relationships
                rel_map = {
                    '/P22': ('parent', 'father'),
                    '/P25': ('parent', 'mother'),
                    '/P26': ('spouse', 'spouse'),
                    '/P40': ('child', 'child'),
                }
                for prop_suffix, (rel_type, rel_label) in rel_map.items():
                    if prop.endswith(prop_suffix):
                        persons[qid]["relationships"].append({
                            "type": rel_type,
                            "person_label": row.get('valueLabel', ''),
                            "wikidata_ref": row.get('value', '').rsplit('/', 1)[-1] if row.get('value', '').startswith('http') else None,
                            "source": "wikidata"
                        })
    
    print(f"Loaded {len(persons)} unique persons from Wikidata CSVs")
    return persons


def load_extracted_persons(site_data_dir: Path) -> List[Dict[str, Any]]:
    """Load all extracted persons from pipeline output files."""
    all_persons = []
    
    for json_file in site_data_dir.glob("*.json"):
        if json_file.name in ("authority.json", "wikidata_matches.json"):
            continue
        
        try:
            doc = json.loads(json_file.read_text())
            doc_id = doc.get("doc_id", json_file.stem)
            
            for person in doc.get("persons", []):
                person["_source_doc"] = doc_id
                all_persons.append(person)
        except Exception as e:
            print(f"  Error loading {json_file}: {e}")
    
    print(f"Loaded {len(all_persons)} extracted persons from {site_data_dir}")
    return all_persons


def match_persons(
    authority: Dict[str, Dict],
    wikidata: Dict[str, Dict],
    extracted: List[Dict]
) -> Dict[str, Dict[str, Any]]:
    """
    Match persons across sources using 3-tier strategy.
    Returns unified KG with cross-references.
    """
    # Start with authority as base (most curated)
    unified = dict(authority)
    
    # Build lookup indices
    auth_by_normalized: Dict[str, List[str]] = {}
    for auth_id, person in authority.items():
        for norm in person["names"]["normalized"]:
            if norm not in auth_by_normalized:
                auth_by_normalized[norm] = []
            auth_by_normalized[norm].append(auth_id)
    
    wd_by_normalized: Dict[str, List[str]] = {}
    for qid, person in wikidata.items():
        norm = normalise(person["preferred_label"])
        if norm not in wd_by_normalized:
            wd_by_normalized[norm] = []
        wd_by_normalized[norm].append(qid)
    
    # Match Wikidata to Authority
    matches_found = 0
    for qid, wd_person in wikidata.items():
        wd_norm = normalise(wd_person["preferred_label"])
        
        # Tier 1: Exact normalized match
        if wd_norm in auth_by_normalized:
            auth_ids = auth_by_normalized[wd_norm]
            if len(auth_ids) == 1:
                auth_id = auth_ids[0]
                # Merge Wikidata data into authority record
                unified[auth_id]["identifiers"]["wikidata_qid"] = qid
                unified[auth_id]["provenance"]["sources"].append({
                    "type": "wikidata",
                    "match_type": "exact",
                    "confidence": 1.0
                })
                matches_found += 1
    
    print(f"Found {matches_found} exact Authority↔Wikidata matches")
    
    # Add unmatched Wikidata persons to unified KG
    for qid, wd_person in wikidata.items():
        if "wikidata_qid" not in [p.get("identifiers", {}).get("wikidata_qid") for p in unified.values()]:
            unified[f"WIKIDATA:{qid}"] = wd_person
    
    # Process extracted persons
    for ext_person in extracted:
        name = ext_person.get("name", "")
        if not name or len(name) < 3:
            continue
        
        ext_norm = normalise(name)
        
        # Try to match to existing unified records
        matched = False
        if ext_norm in auth_by_normalized:
            matched = True
        elif ext_norm in wd_by_normalized:
            matched = True
        
        if not matched:
            # Add as new extracted-only person
            person_id = f"EXTRACTED:{slugify(name)}"
            unified[person_id] = {
                "id": person_id,
                "preferred_label": name,
                "identifiers": {},
                "names": {
                    "preferred": name,
                    "variants": [name],
                    "normalized": [ext_norm]
                },
                "bio": {
                    "gender": ext_person.get("gender", "unknown")
                },
                "roles": [],
                "relationships": [],
                "places": [],
                "provenance": {
                    "sources": [{
                        "type": "extraction",
                        "source_file": ext_person.get("_source_doc"),
                        "confidence": ext_person.get("confidence", 0.5)
                    }],
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat()
                },
                "flags": {
                    "needs_review": True
                }
            }
    
    return unified


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "person"


def main():
    repo_root = Path(__file__).parent.parent
    scripts_dir = repo_root / "scripts"
    site_data_dir = repo_root / "site" / "data"
    data_dir = repo_root / "data"
    
    print("=== Building Unified Knowledge Graph ===\n")
    
    # Load sources
    print("1. Loading Outremer authority file...")
    authority = load_outremer_authority(scripts_dir / "outremer_index.json")
    print(f"   Loaded {len(authority)} authority persons\n")
    
    print("2. Loading Wikidata Peerage pre-1500...")
    wikidata = load_wikidata_peerage(scripts_dir / "peerage_pre1500_export")
    print(f"   Loaded {len(wikidata)} Wikidata persons\n")
    
    print("3. Loading extracted persons from pipeline...")
    extracted = load_extracted_persons(site_data_dir)
    
    # Match and merge
    print("\n4. Running matching engine...")
    unified = match_persons(authority, wikidata, extracted)
    
    # Write output
    output_file = data_dir / "unified_kg.json"
    output_file.write_text(json.dumps(unified, ensure_ascii=False, indent=2))
    
    print(f"\n✅ Unified KG written to {output_file}")
    print(f"   Total persons: {len(unified)}")
    
    # Summary stats
    with_wd = sum(1 for p in unified.values() if p.get("identifiers", {}).get("wikidata_qid"))
    with_auth = sum(1 for p in unified.values() if p.get("identifiers", {}).get("outremer_auth"))
    extracted_only = sum(1 for p in unified.values() if p.get("flags", {}).get("needs_review"))
    
    print(f"\n   Breakdown:")
    print(f"   - With Wikidata QID: {with_wd}")
    print(f"   - With Outremer AUTH: {with_auth}")
    print(f"   - Extraction only (needs review): {extracted_only}")


if __name__ == "__main__":
    main()
