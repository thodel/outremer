#!/usr/bin/env python3
"""
filter_ner_noise.py
───────────────────
Post-processing filter for NER extraction output.
Removes bibliographic metadata, modern scholars, and obvious false positives.

Usage:
    python scripts/filter_ner_noise.py --input site/data/rileysmith-*.json --output site/data/filtered/
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Set


# === BLACKLIST: Terms that should NEVER be extracted as persons ===
BIBLIOGRAPHIC_NOISE = {
    # Journal/publisher terms
    "proceedings of", "philosophical society", "american philosophical",
    "university press", "oxford university", "cambridge university",
    "journal of", "review", "historical review", "english historical",
    "vol", "volume", "issue", "no", "number", "pp", "pages",
    "published", "publication", "publisher", "copyright", "all rights reserved",
    "isbn", "doi", "issn",
    
    # Modern academic terms
    "author", "editor", "translator", "introduction", "preface", "foreword",
    "bibliography", "references", "works cited", "index", "appendix",
    "chapter", "section", "part", "book", "article", "thesis", "dissertation",
    "professor", "prof", "dr", "mr", "mrs", "ms", "phd", "ma", "ba",
    
    # Library/catalog metadata
    "stable url", "jstor", "accessed", "downloaded", "terms of use",
    "pdf", "text", "preview", "abstract",
    
    # Common false positives
    "source", "title", "language", "doc type", "extracted", "extraction",
    "person", "persons", "people", "group", "collective",
    
    # Medieval text noise (headers, incipits)
    "incipit", "explicit", "folio", "manuscript", "ms", "mss",
    "recto", "verso", "column", "line",
}

# Patterns that indicate non-person entities
NOISE_PATTERNS = [
    r'^\d+$',  # Just numbers
    r'^vol\.?\s*\d+$',  # Volume numbers
    r'^pp\.?\s*\d+',  # Page ranges
    r'^\d{4}$',  # Years standing alone
    r'^(the|a|an)\s+\w+$',  # Generic noun phrases
    r'\b(see|cf|ibid|op\.? cit)\.?$',  # Citation abbreviations
]

# === WHITELIST: Medieval naming patterns (high confidence) ===
MEDIEVAL_PATTERNS = [
    r'\b(I{1,3}|IV|IX|V?I{0,3})\b',  # Regnal numbers
    r'\bof\s+\w+',  # Toponymic (of Jerusalem, of Flanders)
    r'\bde\s+\w+',  # Norman/French (de Montfort, de Beaumont)
    r'\bvan\s+\w+',  # Dutch/Flemish
    r'\bvon\s+\w+',  # German
    r'\bal[-\s]?\w+',  # Arabic (al-Malik, al-Andalusi)
    r'\bibn\s+\w+',  # Arabic patronymic
    r'\bmac\s+\w+',  # Scottish/Irish
    r"\b(o'|fitz)\s*\w+",  # Irish/Norman
    r'\ble\s+\w+',  # French epithet (le Lion, le Gros)
    r'\bthe\s+\w+',  # English epithet (the Bold, the Younger)
    r'\bsaint\s+\w+',  # Hagionyms
    r'\bst\.\s+\w+',
    r'\bking\s+', r'\bqueen\s+', r'\bcount\s+', r'\bduke\s+',
    r'\bbishop\s+', r'\bpope\s+', r'\bemperor\s+', r'\bsultan\s+',
]


def is_bibliographic_noise(name: str) -> bool:
    """Check if name is likely bibliographic metadata."""
    name_lower = name.lower().strip()
    
    # Exact blacklist match
    if name_lower in BIBLIOGRAPHIC_NOISE:
        return True
    
    # Partial matches for multi-word terms
    for term in BIBLIOGRAPHIC_NOISE:
        if ' ' in term and term in name_lower:
            return True
    
    # Regex patterns
    for pattern in NOISE_PATTERNS:
        if re.match(pattern, name_lower):
            return True
    
    return False


def has_medieval_pattern(name: str) -> bool:
    """Check if name matches medieval naming conventions."""
    for pattern in MEDIEVAL_PATTERNS:
        if re.search(pattern, name, re.IGNORECASE):
            return True
    return False


def is_likely_modern_scholar(person: dict, context: str = "") -> bool:
    """Detect modern scholars based on context and metadata."""
    name = person.get("name", "")
    role = person.get("role", "")
    confidence = person.get("confidence", 1.0)
    
    # Explicitly marked as modern author
    if role == "modern author":
        return True
    
    # Low confidence + academic context
    if confidence <= 0.15:
        return True
    
    # Context clues
    context_lower = context.lower()
    modern_indicators = [
        "argues", "claims", "suggests", "writes", "publishes",
        "according to", "cf.", "see", "edition", "translation",
        "trans.", "ed.", "intro", "footnote", "citation"
    ]
    
    for indicator in modern_indicators:
        if indicator in context_lower:
            return True
    
    return False


def filter_persons(doc: dict, *, strict: bool = False) -> dict:
    """
    Filter extracted persons from a document.
    
    Args:
        doc: Document JSON from pipeline
        strict: If True, also filter low-confidence extractions
    
    Returns:
        Filtered document with noisy persons removed
    """
    original_count = len(doc.get("persons", []))
    filtered_persons = []
    filtered_links = []
    
    for person in doc.get("persons", []):
        name = person.get("name", "")
        
        # Skip empty or too short
        if not name or len(name.strip()) < 2:
            continue
        
        # Check blacklist
        if is_bibliographic_noise(name):
            continue
        
        # Check for modern scholar markers
        context = person.get("context", "")
        if is_likely_modern_scholar(person, context):
            continue
        
        # In strict mode, require medieval patterns or high confidence
        if strict:
            confidence = person.get("confidence", 0.0)
            if confidence < 0.5 and not has_medieval_pattern(name):
                continue
        
        filtered_persons.append(person)
    
    # Also filter links section
    for link in doc.get("links", []):
        person_name = link.get("person", "")
        
        if is_bibliographic_noise(person_name):
            continue
        
        # Keep link if it has candidates or high confidence
        if link.get("status") in ("high", "medium") or link.get("candidates"):
            filtered_links.append(link)
        elif link.get("status") == "low" and link.get("top_candidate"):
            # Keep low confidence only if there's a candidate
            filtered_links.append(link)
    
    # Update document
    doc["persons"] = filtered_persons
    doc["links"] = filtered_links
    doc["_filter_metadata"] = {
        "original_persons": original_count,
        "filtered_persons": len(filtered_persons),
        "removed": original_count - len(filtered_persons),
        "original_links": len(doc.get("links", [])),
        "filtered_links": len(filtered_links)
    }
    
    return doc


def process_file(input_path: Path, output_path: Path, strict: bool = False):
    """Process a single document file."""
    doc = json.loads(input_path.read_text())
    filtered = filter_persons(doc, strict=strict)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2))
    
    meta = filtered.get("_filter_metadata", {})
    print(f"  {input_path.name}: {meta.get('original_persons', 0)} → {meta.get('filtered_persons', 0)} persons ({meta.get('removed', 0)} removed)")


def main():
    parser = argparse.ArgumentParser(description="Filter NER noise from Outremer extraction output")
    parser.add_argument("--input", "-i", required=True, help="Input file or directory")
    parser.add_argument("--output", "-o", required=True, help="Output file or directory")
    parser.add_argument("--strict", action="store_true", help="Strict mode: require medieval patterns or high confidence")
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    if input_path.is_file():
        if output_path.suffix:
            process_file(input_path, output_path, args.strict)
        else:
            process_file(input_path, output_path / input_path.name, args.strict)
    elif input_path.is_dir():
        print(f"Processing directory: {input_path}")
        for json_file in input_path.glob("*.json"):
            if json_file.name in ("authority.json", "wikidata_matches.json"):
                continue
            process_file(json_file, output_path / json_file.name, args.strict)
        print(f"\n✅ Output written to {output_path}")
    else:
        print(f"Error: {input_path} not found")
        exit(1)


if __name__ == "__main__":
    main()
