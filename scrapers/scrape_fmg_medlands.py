#!/usr/bin/env python3
"""
FMG MedLands Crusader Nobility Scraper

Scrapes Foundation for Medieval Genealogy (MedLands) for crusader nobility data.
Target sections: Kings of Jerusalem, Counts of Tripoli, Princes of Antioch, Counts of Edessa, Byzantium.

Output: data/fmg/fmg_medlands_crusaders.json
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import time
import random
from datetime import datetime
from pathlib import Path

BASE_URL = "http://fmg.ac/Projects/MedLands/"

# Use browser-like headers to avoid being blocked
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Target pages with their corresponding titles/regions
TARGET_PAGES = [
    {"file": "JERUSALEM.htm", "region": "Kingdom of Jerusalem", "title_filter": "KINGS"},
    {"file": "TRIPOLI.htm", "region": "County of Tripoli", "title_filter": "COMTES"},
    {"file": "ANTIOCH.htm", "region": "Principality of Antioch", "title_filter": "PRINCES"},
    {"file": "EDESSA.htm", "region": "County of Edessa", "title_filter": "COMTES"},
    {"file": "BYZANTIUM.htm", "region": "Byzantine Empire", "title_filter": "EMPERORS"},
]

def extract_name(text):
    """Extract person name from MedLands format (usually bold or at start of paragraph)."""
    # MedLands often formats names as: **NAME**, fl. dates
    # Or: NAME, title...
    
    # Try to find text in bold (often the name)
    name_match = re.search(r'\*\*([^*]+)\*\*', text)
    if name_match:
        return name_match.group(1).strip()
    
    # Otherwise, take text before first comma or before floruit dates
    name_match = re.search(r'^([A-Z][^,]+?)(?:,|\s+fl\.|\s+\(|$)', text, re.IGNORECASE)
    if name_match:
        return name_match.group(1).strip()
    
    return None

def extract_floruit(text):
    """Extract floruit dates (fl. YYYY-YYYY or similar patterns)."""
    # Pattern: fl. 1100-1118 or flourished 1095-1099
    match = re.search(r'(?:fl\.|flourished)\s*(\d{4})(?:[-–](\d{4}))?', text, re.IGNORECASE)
    if match:
        start = match.group(1)
        end = match.group(2) if match.group(2) else start
        return f"{start}-{end}" if end != start else start
    
    # Pattern: died YYYY or d. YYYY
    match = re.search(r'(?:died|d\.)\s*(\d{4})', text, re.IGNORECASE)
    if match:
        return f"?-{match.group(1)}"
    
    # Pattern: born YYYY or b. YYYY
    match = re.search(r'(?:born|b\.)\s*(\d{4})', text, re.IGNORECASE)
    if match:
        return f"{match.group(1)}-?"
    
    return None

def extract_title(text, region):
    """Extract title from the text based on region context."""
    title_patterns = [
        (r'king\s+of\s+(\w+(?:\s+\w+)?)', 'King of {}'),
        (r'queen\s+of\s+(\w+(?:\s+\w+)?)', 'Queen of {}'),
        (r'count\s+of\s+(\w+(?:\s+\w+)?)', 'Count of {}'),
        (r'countess\s+of\s+(\w+(?:\s+\w+)?)', 'Countess of {}'),
        (r'prince\s+of\s+(\w+(?:\s+\w+)?)', 'Prince of {}'),
        (r'princess\s+of\s+(\w+(?:\s+\w+)?)', 'Princess of {}'),
        (r'emperor\s+(?:of\s+)?(\w*(?:\s+\w*)?)', 'Emperor{}'),
        (r'empress\s+(?:of\s+)?(\w*(?:\s+\w*)?)', 'Empress{}'),
        (r'lord\s+of\s+(\w+(?:\s+\w+)?)', 'Lord of {}'),
        (r'lady\s+of\s+(\w+(?:\s+\w+)?)', 'Lady of {}'),
    ]
    
    for pattern, template in title_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            place = match.group(1) if match.lastindex else ""
            if '{}' in template:
                return template.format(place.title())
            return template + (f" {place.title()}" if place else "")
    
    # Default to region-based title
    return f"Noble of {region}"

def extract_relations(text):
    """Extract family relations mentioned in the text."""
    relations = []
    
    relation_patterns = [
        (r'(?:son|daughter)\s+of\s+([^,.]+)', 'child_of'),
        (r'(?:brother|sister)\s+of\s+([^,.]+)', 'sibling_of'),
        (r'(?:husband|wife|spouse)\s+of\s+([^,.]+)', 'spouse_of'),
        (r'(?:father|mother)\s+of\s+([^,.]+)', 'parent_of'),
        (r'married\s+(?:to\s+)?([^,.]+)', 'spouse_of'),
    ]
    
    for pattern, rel_type in relation_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            name = match.strip().rstrip('.,;')
            # Clean up common artifacts
            name = re.sub(r'\s+(?:fl\.|d\.|b\.).*$', '', name)
            if name and len(name) > 2:
                relations.append({
                    "type": rel_type,
                    "name": name
                })
    
    return relations

def extract_sources(text):
    """Extract source references from the text."""
    sources = []
    
    # Common medieval source abbreviations
    source_patterns = [
        r'RHC\s+Hist\.\s+Occ\.',
        r'William\s+of\s+Tyre',
        r'Fulcher\s+of\s+Chartres',
        r'Albert\s+of\s+Aachen',
        r'Orderic\s+Vitalis',
        r'Robert\s+the\s+Monk',
        r'Guibert\s+of\s+Nogent',
        r'Baldric\s+of\s+Dol',
        r'Raymond\s+d\'Aguilers',
        r'Peter\s+Tudebode',
        r'Ibn\s+al-Athīr',
        r'Usāma\s+ibn\s+Munqidh',
        r'Cartulaire\s+général',
        r'Delaville\s+Le\s+Roulx',
    ]
    
    for pattern in source_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            sources.append(pattern)
    
    return sources if sources else ["MedLands"]

def parse_medlands_page(url, region_info, session):
    """Parse a single MedLands page and extract person data."""
    persons = []
    
    # Retry logic with exponential backoff and longer delays
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Add significant delay between requests (be very polite)
            if attempt > 0:
                delay = 5 + random.uniform(2, 5)
                print(f"   Waiting {delay:.1f}s before retry...")
                time.sleep(delay)
            
            resp = session.get(url, timeout=60)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                print(f"  ⚠️  Error fetching {url} after {max_retries} attempts: {e}")
                print(f"  💡 The fmg.ac server may be blocking automated requests.")
                print(f"  💡 Try downloading pages manually from: {BASE_URL}")
                return persons
            print(f"  ⚠️  Attempt {attempt + 1} failed: {type(e).__name__}")
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # MedLands uses <p class="Normal"> or <p class="MsoNormal"> for content paragraphs
    paragraphs = soup.find_all('p', class_=re.compile(r'Normal|MsoNormal', re.IGNORECASE))
    
    current_person = None
    
    for p in paragraphs:
        text = p.get_text(strip=True)
        if not text or len(text) < 20:
            continue
        
        # Check if this paragraph starts a new person entry
        # Usually marked by bold name or specific formatting
        name = extract_name(text)
        
        if name:
            # Save previous person if exists
            if current_person:
                persons.append(current_person)
            
            # Start new person
            current_person = {
                "name": name,
                "floruit": extract_floruit(text),
                "title": extract_title(text, region_info["region"]),
                "family": None,  # Would need more sophisticated parsing
                "relations": extract_relations(text),
                "sources": extract_sources(text),
                "metadata": {
                    "source_url": url,
                    "region": region_info["region"],
                    "scraped_at": datetime.now().isoformat()
                }
            }
        elif current_person:
            # Continue adding info to current person (relations, etc.)
            more_relations = extract_relations(text)
            for rel in more_relations:
                if rel not in current_person["relations"]:
                    current_person["relations"].append(rel)
            
            # Add sources if found
            more_sources = extract_sources(text)
            for src in more_sources:
                if src not in current_person["sources"]:
                    current_person["sources"].append(src)
    
    # Don't forget the last person
    if current_person:
        persons.append(current_person)
    
    return persons

def main():
    print("🏰 FMG MedLands Crusader Nobility Scraper")
    print("=" * 50)
    
    # Create a session to maintain cookies
    session = requests.Session()
    session.headers.update(HEADERS)
    
    # Initial delay before starting (be polite)
    print("\n⏳ Waiting 3 seconds before starting (being polite to the server)...")
    time.sleep(3)
    
    all_persons = []
    
    for i, page_info in enumerate(TARGET_PAGES):
        if i > 0:
            # Delay between pages
            delay = 3 + random.uniform(1, 3)
            print(f"\n⏳ Waiting {delay:.1f}s before next page...")
            time.sleep(delay)
        
        url = BASE_URL + page_info["file"]
        print(f"\n📜 Scraping {page_info['region']}...")
        print(f"   URL: {url}")
        
        persons = parse_medlands_page(url, page_info, session)
        print(f"   ✅ Found {len(persons)} persons")
        
        all_persons.extend(persons)
    
    # Build output structure
    output = {
        "source": "FMG MedLands",
        "source_url": BASE_URL,
        "scraped_at": datetime.now().isoformat(),
        "total_persons": len(all_persons),
        "regions": [p["region"] for p in TARGET_PAGES],
        "persons": all_persons
    }
    
    # Ensure output directory exists
    output_dir = Path(__file__).parent.parent / "data" / "fmg"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Write output
    output_file = output_dir / "fmg_medlands_crusaders.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print("\n" + "=" * 50)
    print(f"✅ Complete! Extracted {len(all_persons)} persons")
    print(f"📁 Output: {output_file}")
    
    # Print summary by region
    print("\n📊 Summary by region:")
    region_counts = {}
    for p in all_persons:
        region = p["metadata"]["region"]
        region_counts[region] = region_counts.get(region, 0) + 1
    
    for region, count in sorted(region_counts.items()):
        print(f"   {region}: {count}")

if __name__ == "__main__":
    main()
