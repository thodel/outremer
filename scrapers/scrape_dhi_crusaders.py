#!/usr/bin/env python3
"""
DHI Crusaders Database Scraper

Scrapes "A Database of Crusaders to the Holy Land, 1095-1149" from DHI Sheffield.
Source: https://www.dhi.ac.uk/crusaders/

Output: data/dhi/dhi_crusaders_raw.json (raw scraped data)
        data/dhi/dhi_crusaders_unified.json (mapped to Outremer KG schema)

The database contains ~1100 records of crusaders from First Crusade (1096-1099) 
to Second Crusade (1145-1149).
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import time
import random
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

BASE_URL = "https://www.dhi.ac.uk/crusaders/"
PERSON_URL = "https://www.dhi.ac.uk/crusaders/person/"

# Use browser-like headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "dhi"

def fetch_person_page(person_id, session=None):
    """Fetch a single person page."""
    url = f"{PERSON_URL}?id={person_id}"
    
    # Use session if provided for cookie persistence
    req_session = session if session else requests.Session()
    
    try:
        resp = req_session.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        
        if resp.status_code == 200:
            # Check if we got actual content vs. block page
            if 'Database of Crusaders' in resp.text or '<h1>' in resp.text:
                return resp.text
            else:
                print(f"  ID {person_id}: Got response but content looks blocked")
                return None
        elif resp.status_code == 403:
            print(f"  ID {person_id}: 403 Forbidden (bot protection)")
            return None
        elif resp.status_code == 404:
            return None
        else:
            print(f"  ID {person_id}: HTTP {resp.status_code}")
            return None
    except Exception as e:
        print(f"  ID {person_id}: Error - {e}")
        return None

def parse_person_html(html, person_id):
    """Parse person HTML and extract structured data."""
    soup = BeautifulSoup(html, 'html.parser')
    page_div = soup.find('div', class_='page')
    if not page_div:
        return None
    
    data = {
        "source_id": f"DHI:{person_id}",
        "source_url": f"{PERSON_URL}?id={person_id}",
        "scraped_at": datetime.now().isoformat(),
        "fields": {}
    }
    
    # Extract name (h1)
    h1 = page_div.find('h1')
    if h1:
        data["fields"]["name"] = h1.get_text(strip=True)
    
    # Extract all label/value pairs
    for row in page_div.find_all('div', class_='row'):
        label_div = row.find('div', class_='label')
        value_div = row.find('div', class_='value')
        
        if label_div and value_div:
            label = label_div.get_text(strip=True)
            # Get text content but preserve structure
            value = value_div.get_text(strip=True)
            # Remove the glyphicon list icon text if present
            value = re.sub(r'\s*\ue056\s*', '', value)
            
            # Normalize label to snake_case key
            key = label.lower().replace(' ', '_').replace('(', '').replace(')', '')
            key = re.sub(r'_+', '_', key).strip('_')
            
            data["fields"][key] = value
    
    # Extract family relationships (special handling)
    if 'family' in data["fields"]:
        data["relationships"] = parse_family(data["fields"]["family"])
    
    # Extract crusade data (under <h2>Crusades</h2>)
    crusades_section = page_div.find('h2', string='Crusades')
    if crusades_section:
        data["crusades"] = []
        current_crusade = {}
        for sibling in crusades_section.find_next_siblings():
            if sibling.name == 'h2':
                break
            if sibling.get('class') == ['row']:
                label_div = sibling.find('div', class_='label')
                value_div = sibling.find('div', class_='value')
                if label_div and value_div:
                    key = label_div.get_text(strip=True).lower().replace(' ', '_')
                    value = value_div.get_text(strip=True)
                    current_crusade[key] = value
        if current_crusade:
            data["crusades"].append(current_crusade)
    
    return data

def parse_family(family_text):
    """Parse family relationships from text."""
    relationships = []
    # Pattern: "brother: Name (description), Sister: Name"
    rel_patterns = [
        (r'brother[s]?:\s*([^,(]+)(?:\s*\(([^)]+)\))?', 'brother'),
        (r'sister[s]?:\s*([^,(]+)(?:\s*\(([^)]+)\))?', 'sister'),
        (r'father[s]?:\s*([^,(]+)(?:\s*\(([^)]+)\))?', 'father'),
        (r'mother[s]?:\s*([^,(]+)(?:\s*\(([^)]+)\))?', 'mother'),
        (r'son[s]?:\s*([^,(]+)(?:\s*\(([^)]+)\))?', 'son'),
        (r'daughter[s]?:\s*([^,(]+)(?:\s*\(([^)]+)\))?', 'daughter'),
        (r'wife(?:s)?:\s*([^,(]+)(?:\s*\(([^)]+)\))?', 'spouse'),
        (r'husband[s]?:\s*([^,(]+)(?:\s*\(([^)]+)\))?', 'spouse'),
        (r'uncle[s]?:\s*([^,(]+)(?:\s*\(([^)]+)\))?', 'uncle'),
    ]
    
    for pattern, rel_type in rel_patterns:
        matches = re.findall(pattern, family_text, re.IGNORECASE)
        for match in matches:
            name = match[0].strip()
            description = match[1].strip() if len(match) > 1 and match[1] else None
            if name:
                rel = {
                    "type": rel_type,
                    "name": name
                }
                if description:
                    rel["description"] = description
                relationships.append(rel)
    
    return relationships

def map_to_unified_kg(raw_data):
    """Map scraped DHI data to Outremer unified KG schema."""
    fields = raw_data.get("fields", {})
    
    # Extract name components
    full_name = fields.get("name", "Unknown")
    
    # Try to parse name pattern (e.g., "Achard unmarried of Marseilles")
    name_parts = {
        "preferred": full_name,
        "given": None,
        "toponym": None,
        "pattern": None
    }
    
    # Pattern: "Name [descriptor] of Place"
    match = re.match(r'^([A-Z][a-z]+)(?:\s+([^o]+))?\s+of\s+(.+)$', full_name)
    if match:
        name_parts["given"] = match.group(1)
        if match.group(2):
            name_parts["descriptor"] = match.group(2).strip()
        name_parts["toponym"] = match.group(3)
        name_parts["pattern"] = "given_of_toponym"
    else:
        # Just use the full name
        name_parts["given"] = full_name.split()[0] if full_name else None
    
    # Generate variants
    variants = generate_name_variants(name_parts)
    
    # Extract roles
    roles = []
    role_text = fields.get("role", "")
    if role_text:
        # Parse "Archbishop (cleric)" -> role + type
        match = re.match(r'^([^(]+)(?:\s*\(([^)]+)\))?', role_text)
        if match:
            roles.append({
                "role": match.group(1).strip(),
                "type": match.group(2).strip() if match.group(2) else "unknown"
            })
    
    # Extract places
    places = []
    country = fields.get("country_and_region_of_origin", "")
    if country:
        # Remove the link text and extract country/region
        country_clean = country.split('\n')[0].strip()
        if country_clean:
            places.append({
                "type": "origin",
                "label": country_clean
            })
    
    title = fields.get("specific_title", "")
    if title:
        places.append({
            "type": "title",
            "label": title
        })
    
    # Extract bio info
    bio = {}
    if fields.get("gender_and_marital_statusa"):
        bio["gender"] = fields.get("gender_and_marital_statusa")
    
    # Extract crusade participation
    crusades = raw_data.get("crusades", [])
    expeditions = []
    for crusade in crusades:
        exp = {}
        if crusade.get("expedition"):
            exp["name"] = crusade.get("expedition")
        if crusade.get("probability_of_participation"):
            exp["probability"] = crusade.get("probability_of_participation")
        if crusade.get("consequences_of_expedition"):
            exp["outcome"] = crusade.get("consequences_of_expedition")
        if crusade.get("actions"):
            exp["actions"] = crusade.get("actions")
        if crusade.get("contingent_leader"):
            exp["leader"] = crusade.get("contingent_leader")
        if crusade.get("financial_arrangements"):
            exp["finance"] = crusade.get("financial_arrangements")
        if exp:
            expeditions.append(exp)
    
    # Extract sources
    sources = []
    source_text = fields.get("sources", "")
    if source_text:
        # Split by periods to get individual citations
        citations = [s.strip() for s in source_text.split('.') if s.strip()]
        for citation in citations:
            if citation:
                sources.append({
                    "type": "primary_source",
                    "citation": citation.rstrip('.')
                })
    
    # Build unified record
    unified = {
        "id": raw_data["source_id"],
        "preferred_label": full_name,
        "identifiers": {
            "dhi_id": raw_data["source_id"].replace("DHI:", ""),
            "dhi_url": raw_data["source_url"],
            "outremer_auth": None  # Will be assigned during merge
        },
        "names": {
            "preferred": full_name,
            "variants": variants,
            "normalized": [v.lower() for v in variants],
            "parsed": name_parts
        },
        "bio": bio,
        "roles": roles,
        "relationships": raw_data.get("relationships", []),
        "places": places,
        "expeditions": expeditions,
        "provenance": {
            "sources": [
                {
                    "type": "external_database",
                    "source_url": raw_data["source_url"],
                    "confidence": 0.95,
                    "scraped_at": raw_data["scraped_at"]
                }
            ],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        },
        "flags": {
            "source": "dhi_crusaders_db",
            "participation_confirmed": any(
                exp.get("probability") == "Certain" for exp in expeditions
            )
        }
    }
    
    return unified

def generate_name_variants(name_parts):
    """Generate name variants for matching."""
    variants = set()
    given = name_parts.get("given", "")
    toponym = name_parts.get("toponym", "")
    descriptor = name_parts.get("descriptor", "")
    
    if given:
        variants.add(given)
    
    if given and toponym:
        variants.add(f"{given} of {toponym}")
        variants.add(f"{given}, {toponym}")
        variants.add(f"{given} ({toponym})")
        variants.add(f"{toponym}'s {given}")
    
    if descriptor:
        variants.add(f"{given} {descriptor}")
        if toponym:
            variants.add(f"{given} {descriptor} of {toponym}")
    
    return sorted(list(variants))

def discover_person_ids(max_id=2000):
    """Discover valid person IDs by probing sequential IDs."""
    valid_ids = []
    print(f"Discovering person IDs (1-{max_id})...")
    
    for i in range(1, max_id + 1):
        html = fetch_person_page(i)
        if html:
            valid_ids.append(i)
            if len(valid_ids) % 100 == 0:
                print(f"  Found {len(valid_ids)} persons so far...")
        time.sleep(0.2)  # Rate limiting
    
    print(f"Found {len(valid_ids)} valid person IDs")
    return valid_ids

def scrape_all(output_raw=True, output_unified=True):
    """Main scraping function."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Discover or load person IDs
    id_cache = OUTPUT_DIR / "dhi_person_ids.json"
    if id_cache.exists():
        with open(id_cache) as f:
            person_ids = json.load(f)
        print(f"Loaded {len(person_ids)} person IDs from cache")
    else:
        person_ids = discover_person_ids(1500)
        with open(id_cache, 'w') as f:
            json.dump(person_ids, f, indent=2)
    
    # Scrape all persons
    raw_records = []
    unified_records = {}
    
    for i, person_id in enumerate(person_ids):
        print(f"[{i+1}/{len(person_ids)}] Fetching person ID {person_id}...")
        
        html = fetch_person_page(person_id)
        if not html:
            print(f"  Skipped (no page)")
            continue
        
        raw = parse_person_html(html, person_id)
        if raw:
            raw_records.append(raw)
            
            # Map to unified schema
            unified = map_to_unified_kg(raw)
            unified_records[unified["id"]] = unified
        
        # Rate limiting
        time.sleep(0.3 + random.uniform(0, 0.2))
    
    # Save outputs
    if output_raw:
        raw_file = OUTPUT_DIR / "dhi_crusaders_raw.json"
        with open(raw_file, 'w', encoding='utf-8') as f:
            json.dump({
                "source": "DHI Crusaders Database",
                "source_url": BASE_URL,
                "scraped_at": datetime.now().isoformat(),
                "record_count": len(raw_records),
                "records": raw_records
            }, f, indent=2, ensure_ascii=False)
        print(f"\nSaved raw data: {raw_file}")
    
    if output_unified:
        unified_file = OUTPUT_DIR / "dhi_crusaders_unified.json"
        with open(unified_file, 'w', encoding='utf-8') as f:
            json.dump({
                "schema": "outremer-unified-kg-v1",
                "source": "DHI Crusaders Database (mapped)",
                "mapped_at": datetime.now().isoformat(),
                "record_count": len(unified_records),
                "persons": unified_records
            }, f, indent=2, ensure_ascii=False)
        print(f"Saved unified KG: {unified_file}")
    
    return raw_records, unified_records

def scrape_single(person_id):
    """Scrape a single person for testing."""
    print(f"Fetching person ID {person_id}...")
    html = fetch_person_page(person_id)
    
    if not html:
        print("Person not found or error fetching")
        return None
    
    raw = parse_person_html(html, person_id)
    if raw:
        print("\n=== Raw Data ===")
        print(json.dumps(raw, indent=2, ensure_ascii=False))
        
        unified = map_to_unified_kg(raw)
        print("\n=== Unified KG ===")
        print(json.dumps(unified, indent=2, ensure_ascii=False))
        
        return unified
    
    return None

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--single":
            person_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            scrape_single(person_id)
        elif sys.argv[1] == "--discover":
            max_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
            discover_person_ids(max_id)
        elif sys.argv[1] == "--help":
            print("""
DHI Crusaders Database Scraper

Usage:
  python scrape_dhi_crusaders.py              # Scrape all persons
  python scrape_dhi_crusaders.py --single ID  # Scrape single person (for testing)
  python scrape_dhi_crusaders.py --discover N # Discover IDs up to N
  python scrape_dhi_crusaders.py --help       # Show this help

Output:
  data/dhi/dhi_crusaders_raw.json      - Raw scraped data
  data/dhi/dhi_crusaders_unified.json  - Mapped to Outremer KG schema
  data/dhi/dhi_person_ids.json         - Cached list of valid person IDs
""")
    else:
        scrape_all()
