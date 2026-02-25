#!/usr/bin/env python3
"""
FMG MedLands Offline Parser

Parses locally downloaded MedLands HTML files.
Use this when automated scraping is blocked by the server.

Usage:
  1. Download pages manually from http://fmg.ac/Projects/MedLands/
  2. Save to data/fmg/raw/ directory
  3. Run: python scrapers/parse_fmg_offline.py
"""

import json
import re
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

# Configuration
RAW_DIR = Path(__file__).parent.parent / "data" / "fmg" / "raw"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "fmg" / "fmg_medlands_crusaders.json"

# Files to parse (must be downloaded manually)
# Note: Will also accept _SAMPLE.htm files for testing
TARGET_FILES = [
    {"file": "JERUSALEM.htm", "region": "Kingdom of Jerusalem", "fallback": "JERUSALEM_SAMPLE.htm"},
    {"file": "TRIPOLI.htm", "region": "County of Tripoli"},
    {"file": "ANTIOCH.htm", "region": "Principality of Antioch"},
    {"file": "EDESSA.htm", "region": "County of Edessa"},
    {"file": "BYZANTIUM.htm", "region": "Byzantine Empire"},
]


def extract_name(text):
    """Extract person name from MedLands format."""
    # Try bold text first (**NAME**)
    name_match = re.search(r'\*\*([^*]+)\*\*', text)
    if name_match:
        return name_match.group(1).strip()
    
    # Take text before first comma or floruit
    name_match = re.search(r'^([A-Z][A-Za-zÀ-ÿ\'\-]+(?:\s+[A-Za-zÀ-ÿ\'\-]+)*(?:\s+(?:de|d\'|von|van|of|le|la|el|ibn|al)\s+[A-Za-zÀ-ÿ\'\-]+)*)(?:,|\s+fl\.|\s+\(|$)', text, re.IGNORECASE)
    if name_match:
        return name_match.group(1).strip()
    
    return None


def extract_floruit(text):
    """Extract floruit dates."""
    # fl. YYYY-YYYY
    match = re.search(r'(?:fl\.|flourished)\s*(\d{4})(?:[-–](\d{4}))?', text, re.IGNORECASE)
    if match:
        start = match.group(1)
        end = match.group(2) if match.group(2) else start
        return f"{start}-{end}" if end != start else start
    
    # died YYYY
    match = re.search(r'(?:died|d\.)\s*(\d{4})', text, re.IGNORECASE)
    if match:
        return f"?-{match.group(1)}"
    
    # born YYYY
    match = re.search(r'(?:born|b\.)\s*(\d{4})', text, re.IGNORECASE)
    if match:
        return f"{match.group(1)}-?"
    
    return None


def extract_title(text, region):
    """Extract title from text."""
    patterns = [
        (r'king\s+of\s+(\w+(?:\s+\w+)?)', 'King of {}'),
        (r'queen\s+of\s+(\w+(?:\s+\w+)?)', 'Queen of {}'),
        (r'count\s+of\s+(\w+(?:\s+\w+)?)', 'Count of {}'),
        (r'countess\s+of\s+(\w+(?:\s+\w+)?)', 'Countess of {}'),
        (r'prince\s+of\s+(\w+(?:\s+\w+)?)', 'Prince of {}'),
        (r'princess\s+of\s+(\w+(?:\s+\w+)?)', 'Princess of {}'),
        (r'emperor\s+(?:of\s+)?(\w*)', 'Emperor{}'),
        (r'empress\s+(?:of\s+)?(\w*)', 'Empress{}'),
        (r'lord\s+of\s+(\w+(?:\s+\w+)?)', 'Lord of {}'),
        (r'lady\s+of\s+(\w+(?:\s+\w+)?)', 'Lady of {}'),
    ]
    
    for pattern, template in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            place = match.group(1) if match.lastindex else ""
            if '{}' in template:
                return template.format(place.title())
            return template + (f" {place.title()}" if place else "")
    
    return f"Noble of {region}"


def extract_relations(text):
    """Extract family relations."""
    relations = []
    
    patterns = [
        (r'(?:son|daughter)\s+of\s+([^,.]+)', 'child_of'),
        (r'(?:brother|sister)\s+of\s+([^,.]+)', 'sibling_of'),
        (r'(?:husband|wife|spouse)\s+of\s+([^,.]+)', 'spouse_of'),
        (r'married\s+(?:to\s+)?([^,.]+)', 'spouse_of'),
    ]
    
    for pattern, rel_type in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            name = match.strip().rstrip('.,;')
            name = re.sub(r'\s+(?:fl\.|d\.|b\.).*$', '', name)
            if name and len(name) > 2:
                relations.append({"type": rel_type, "name": name})
    
    return relations


def extract_sources(text):
    """Extract source references."""
    sources = []
    
    source_patterns = [
        r'RHC\s+Hist\.\s+Occ\.',
        r'William\s+of\s+Tyre',
        r'Fulcher\s+of\s+Chartres',
        r'Albert\s+of\s+Aachen',
        r'Orderic\s+Vitalis',
        r'Cartulaire\s+général',
        r'Delaville\s+Le\s+Roulx',
    ]
    
    for pattern in source_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            sources.append(pattern)
    
    return sources if sources else ["MedLands"]


def parse_html_file(filepath, region_info):
    """Parse a single HTML file."""
    persons = []
    
    if not filepath.exists():
        return persons
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    soup = BeautifulSoup(content, 'html.parser')
    paragraphs = soup.find_all('p', class_=re.compile(r'Normal|MsoNormal', re.IGNORECASE))
    
    current_person = None
    
    for p in paragraphs:
        text = p.get_text(strip=True)
        if not text or len(text) < 20:
            continue
        
        name = extract_name(text)
        
        if name:
            if current_person:
                persons.append(current_person)
            
            current_person = {
                "name": name,
                "floruit": extract_floruit(text),
                "title": extract_title(text, region_info["region"]),
                "family": None,
                "relations": extract_relations(text),
                "sources": extract_sources(text),
                "metadata": {
                    "source_file": str(filepath.name),
                    "region": region_info["region"],
                    "parsed_at": datetime.now().isoformat()
                }
            }
        elif current_person:
            more_relations = extract_relations(text)
            for rel in more_relations:
                if rel not in current_person["relations"]:
                    current_person["relations"].append(rel)
            
            more_sources = extract_sources(text)
            for src in more_sources:
                if src not in current_person["sources"]:
                    current_person["sources"].append(src)
    
    if current_person:
        persons.append(current_person)
    
    return persons


def main():
    print("🏰 FMG MedLands Offline Parser")
    print("=" * 50)
    print(f"\n📂 Looking for files in: {RAW_DIR}")
    
    # Check if raw directory exists
    if not RAW_DIR.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"ℹ️  Created directory: {RAW_DIR}")
    
    # Check if we have any files to parse
    has_files = False
    for file_info in TARGET_FILES:
        filepath = RAW_DIR / file_info["file"]
        fallback = RAW_DIR / file_info.get("fallback", "") if "fallback" in file_info else None
        if filepath.exists() or (fallback and fallback.exists()):
            has_files = True
            break
    
    if not has_files:
        print(f"\n❌ No HTML files found in {RAW_DIR}")
        print("\n💡 Please download MedLands pages manually:")
        print("   1. Visit http://fmg.ac/Projects/MedLands/")
        print("   2. Download: JERUSALEM.htm, TRIPOLI.htm, ANTIOCH.htm, EDESSA.htm, BYZANTIUM.htm")
        print(f"   3. Save them to: {RAW_DIR}/")
        print("   4. Run this script again")
        print("\n📝 For testing, a sample file (JERUSALEM_SAMPLE.htm) is included.")
        print("   Rename it to JERUSALEM.htm or download the real page.")
        return
    
    all_persons = []
    
    for file_info in TARGET_FILES:
        filepath = RAW_DIR / file_info["file"]
        actual_path = filepath
        
        print(f"\n📜 Parsing {file_info['region']}...")
        
        # Check for fallback if primary doesn't exist
        if not filepath.exists() and "fallback" in file_info:
            fallback = RAW_DIR / file_info["fallback"]
            if fallback.exists():
                print(f"   File: {fallback.name} (sample/test)")
                actual_path = fallback
            else:
                print(f"   File: {filepath.name} (not found, no fallback)")
                continue
        elif not filepath.exists():
            print(f"   File: {filepath.name} (not found)")
            continue
        else:
            print(f"   File: {filepath.name}")
        
        persons = parse_html_file(actual_path, file_info)
        print(f"   ✅ Found {len(persons)} persons")
        
        all_persons.extend(persons)
    
    # Build output
    output = {
        "source": "FMG MedLands",
        "source_url": "http://fmg.ac/Projects/MedLands/",
        "parsed_at": datetime.now().isoformat(),
        "total_persons": len(all_persons),
        "regions": [f["region"] for f in TARGET_FILES],
        "persons": all_persons
    }
    
    # Ensure output directory exists
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Write output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print("\n" + "=" * 50)
    print(f"✅ Complete! Extracted {len(all_persons)} persons")
    print(f"📁 Output: {OUTPUT_FILE}")
    
    # Summary by region
    if all_persons:
        print("\n📊 Summary by region:")
        region_counts = {}
        for p in all_persons:
            region = p["metadata"]["region"]
            region_counts[region] = region_counts.get(region, 0) + 1
        
        for region, count in sorted(region_counts.items()):
            print(f"   {region}: {count}")
    
    print("\n💡 Next step: Integrate into knowledge graph")
    print("   cd /home/th/repos/outremer")
    print("   python scripts/build_unified_kg.py --add-source data/fmg/fmg_medlands_crusaders.json")


if __name__ == "__main__":
    main()
