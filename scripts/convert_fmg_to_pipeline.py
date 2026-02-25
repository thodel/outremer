#!/usr/bin/env python3
"""
convert_fmg_to_pipeline.py
───────────────────────────
Convert FMG MedLands scraper output to Outremer pipeline format.

Input: data/fmg/fmg_medlands_crusaders.json
Output: site/data/fmg_medlands_crusaders.json (pipeline format)
"""

import json
from pathlib import Path
from datetime import datetime


def convert_person(fmg_person, index):
    """Convert a single FMG person to pipeline format."""
    
    # Extract name - clean up artifacts
    name = fmg_person.get("name", "").strip()
    # Remove version info, introductory text
    if name.startswith("v5.") or "Updated" in name or "leaders of" in name.lower():
        return None
    
    # Build variants list
    variants = []
    raw_name = fmg_person.get("name", "")
    if raw_name != name:
        variants.append(raw_name)
    
    # Extract floruit dates
    floruit = fmg_person.get("floruit")
    birth_date = None
    death_date = None
    if floruit:
        if "-" in floruit:
            parts = floruit.split("-")
            if parts[0] and parts[0] != "?":
                birth_date = parts[0]
            if len(parts) > 1 and parts[1] and parts[1] != "?":
                death_date = parts[1]
        elif floruit and floruit != "?":
            # Single date - treat as floruit
            pass
    
    # Convert relations
    relations = []
    for rel in fmg_person.get("relations", []):
        rel_type = rel.get("type", "")
        rel_name = rel.get("name", "").strip()
        # Clean up relation names (remove extra info after parentheses)
        rel_name = rel_name.split("(")[0].strip().rstrip("&").strip()
        if rel_name and len(rel_name) > 2:
            relations.append({
                "type": rel_type,
                "name": rel_name
            })
    
    # Build title/role
    title = fmg_person.get("title", "")
    # Skip entries that are clearly not persons
    if not name or len(name) < 3:
        return None
    if "chapter" in name.lower() or "section" in name.lower():
        return None
    
    # Build pipeline format
    return {
        "id": f"FMG:{index:04d}",
        "name": {
            "label": name,
            "variants": variants
        },
        "dates": {
            "birth": birth_date,
            "death": death_date,
            "floruit": floruit
        },
        "roles": [title] if title else [],
        "relations": relations,
        "sources": fmg_person.get("sources", ["MedLands"]),
        "metadata": {
            "source": "FMG MedLands",
            "source_url": fmg_person.get("metadata", {}).get("source_url", ""),
            "region": fmg_person.get("metadata", {}).get("region", ""),
            "extracted_at": datetime.now().isoformat()
        },
        "flags": {
            "needs_review": True  # FMG data needs manual review
        }
    }


def main():
    repo_root = Path(__file__).parent.parent
    
    input_file = repo_root / "data" / "fmg" / "fmg_medlands_crusaders.json"
    output_file = repo_root / "site" / "data" / "fmg_medlands_crusaders.json"
    
    print("=== Converting FMG MedLands to Pipeline Format ===\n")
    
    # Load FMG data
    print(f"Loading {input_file}...")
    fmg_data = json.loads(input_file.read_text())
    fmg_persons = fmg_data.get("persons", [])
    print(f"  Found {len(fmg_persons)} FMG entries")
    
    # Convert persons
    converted = []
    skipped = 0
    for i, person in enumerate(fmg_persons):
        result = convert_person(person, i)
        if result:
            converted.append(result)
        else:
            skipped += 1
    
    print(f"  Converted: {len(converted)} persons")
    print(f"  Skipped: {skipped} (non-person entries)")
    
    # Create pipeline document format
    pipeline_doc = {
        "doc_id": "fmg_medlands_crusaders",
        "source": "FMG MedLands",
        "source_url": fmg_data.get("source_url", "http://fmg.ac/Projects/MedLands/"),
        "extracted_at": datetime.now().isoformat(),
        "total_persons": len(converted),
        "regions": fmg_data.get("regions", []),
        "persons": converted
    }
    
    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(pipeline_doc, ensure_ascii=False, indent=2))
    
    print(f"\n✅ Output written to: {output_file}")
    print(f"   Size: {output_file.stat().st_size / 1024:.1f} KB")
    print(f"   Persons: {len(converted)}")
    
    # Show sample
    if converted:
        print(f"\n📋 Sample entry:")
        sample = converted[0]
        print(f"   ID: {sample['id']}")
        print(f"   Name: {sample['name']['label']}")
        print(f"   Relations: {len(sample['relations'])}")
        print(f"   Region: {sample['metadata'].get('region', 'N/A')}")


if __name__ == "__main__":
    main()
