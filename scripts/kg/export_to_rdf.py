#!/usr/bin/env python3
"""
export_to_rdf.py
────────────────
Convert unified_kg.json to RDF/Turtle format following SDHSS ontology.

Output: data/unified_kg.ttl (loadable into Apache Jena Fuseki, GraphDB, etc.)

Usage:
  cd /home/th/repos/outremer
  .venv/bin/python3 scripts/kg/export_to_rdf.py
  
Output will be written to data/unified_kg.ttl
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

# ── Constants ──────────────────────────────────────────────────────────────
KG_INPUT = Path("data/unified_kg.json")
KG_OUTPUT = Path("data/unified_kg.ttl")
ONTOLOGY_BASE = "http://sdhss.ch/ontology#"
DATA_BASE = "http://outremer.hodelweb.ch/entity/"

# ── RDF Namespaces ─────────────────────────────────────────────────────────
PREFIXES = """
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix sdhss: <http://sdhss.ch/ontology#> .
@prefix outremer: <http://outremer.hodelweb.ch/entity/> .
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix bio: <http://vocab.org/bio/0.1/> .
@prefix rel: <http://vocab.org/relationship/0.3/> .
@prefix schema: <http://schema.org/> .
"""

# ── Helper Functions ───────────────────────────────────────────────────────
def escape_turtle(s: str) -> str:
    """Escape special characters for Turtle string literals."""
    if not s:
        return '""'
    s = s.replace('\\', '\\\\')
    s = s.replace('"', '\\"')
    s = s.replace('\n', '\\n')
    s = s.replace('\r', '\\r')
    s = s.replace('\t', '\\t')
    return f'"{s}"'


def format_date(date_str: Optional[str]) -> Optional[str]:
    """Convert date string to xsd:gYear format."""
    if not date_str:
        return None
    # Handle various formats
    # "1093" → "1093"^^xsd:gYear
    # "1093-06-21" → "1093"^^xsd:gYear
    # "fl. 1145-1152" → extract first year
    match = re.search(r'\b(\d{4})\b', str(date_str))
    if match:
        return f'"{match.group(1)}"^^xsd:gYear'
    return None


def entity_to_uri(entity_id: str) -> str:
    """Convert internal entity ID to URI."""
    # AUTH:CR1 → outremer:AUTH_CR1
    # WIKIDATA:Q123 → wd:Q123
    # DHI:456 → outremer:DHI_456
    if entity_id.startswith("WIKIDATA:"):
        qid = entity_id.replace("WIKIDATA:", "")
        return f"wd:{qid}"
    else:
        local = entity_id.replace(":", "_").replace("-", "_")
        return f"outremer:{local}"


def normalize_to_uri(s: str) -> str:
    """Convert string to valid URI local part."""
    s = re.sub(r'[^a-zA-Z0-9_]', '_', s)
    s = re.sub(r'_+', '_', s)
    return s.strip('_')


# ── Triple Generation ──────────────────────────────────────────────────────
def generate_person_triples(entity: Dict[str, Any]) -> List[str]:
    """Generate RDF triples for a person entity."""
    triples = []
    
    entity_id = entity.get('id', '')
    uri = entity_to_uri(entity_id)
    
    # Type declaration
    triples.append(f"{uri} a sdhss:Person ;")
    
    # Preferred label
    preferred = entity.get('preferred_label', '')
    if preferred:
        triples.append(f"    sdhss:preferredLabel {escape_turtle(preferred)} ;")
    
    # Variant names
    names = entity.get('names', {})
    variants = names.get('variants', [])
    for variant in variants[:10]:  # Limit to 10 variants
        triples.append(f"    sdhss:variantName {escape_turtle(variant)} ;")
    
    # Normalized forms
    normalized = names.get('normalized', [])
    for norm in normalized[:5]:  # Limit to 5 normalized forms
        triples.append(f"    sdhss:normalizedForm {escape_turtle(norm)} ;")
    
    # Biographical data
    bio = entity.get('bio', {})
    if bio:
        birth = bio.get('birth')
        if isinstance(birth, dict):
            birth = birth.get('date')
        birth_formatted = format_date(birth)
        if birth_formatted:
            triples.append(f"    sdhss:birthDate {birth_formatted} ;")
        
        death = bio.get('death')
        if isinstance(death, dict):
            death = death.get('date')
        death_formatted = format_date(death)
        if death_formatted:
            triples.append(f"    sdhss:deathDate {death_formatted} ;")
        
        floruit = bio.get('floruit')
        if isinstance(floruit, dict):
            floruit = floruit.get('date')
        floruit_formatted = format_date(floruit)
        if floruit_formatted:
            triples.append(f"    sdhss:floruit {floruit_formatted} ;")
        
        gender = bio.get('gender', 'unknown')
        if gender:
            gender_uri = "sdhss:Unknown"
            if gender.lower() in ('m', 'male'):
                gender_uri = "sdhss:Male"
            elif gender.lower() in ('f', 'female'):
                gender_uri = "sdhss:Female"
            triples.append(f"    sdhss:gender {gender_uri} ;")
    
    # Identifiers (external links)
    identifiers = entity.get('identifiers', {})
    if 'wikidata_qid' in identifiers:
        qid = identifiers['wikidata_qid']
        triples.append(f"    sdhss:wikidataQid wd:{qid} ;")
        triples.append(f"    foaf:isPrimaryTopicOf <https://www.wikidata.org/wiki/{qid}> ;")
    
    if 'outremer_auth' in identifiers:
        auth_id = identifiers['outremer_auth']
        triples.append(f"    sdhss:outremerAuthorityId {escape_turtle(auth_id)} ;")
    
    if 'dhi_id' in identifiers:
        dhi_id = identifiers['dhi_id']
        triples.append(f"    sdhss:dhiId {escape_turtle(dhi_id)} ;")
        triples.append(f"    foaf:isPrimaryTopicOf <https://www.dhi.ac.uk/crusaders/person/?id={dhi_id}> ;")
    
    # Roles
    roles = entity.get('roles', [])
    for role in roles[:5]:  # Limit to 5 roles
        role_label = role.get('label', role.get('type', ''))
        if role_label:
            triples.append(f"    sdhss:hasRole {escape_turtle(role_label)} ;")
    
    # Places
    places = entity.get('places', [])
    for place in places[:5]:  # Limit to 5 places
        place_label = place.get('label', '')
        place_type = place.get('type', 'associated_with')
        if place_label:
            triples.append(f"    sdhss:{place_type}Place {escape_turtle(place_label)} ;")
    
    # Provenance
    provenance = entity.get('provenance', {})
    sources = provenance.get('sources', [])
    for source in sources[:3]:  # Limit to 3 sources
        source_type = source.get('type', 'unknown')
        confidence = source.get('confidence', 0.5)
        source_file = source.get('source_file', source.get('source_url', ''))
        
        if source_file:
            triples.append(f"    sdhss:sourceDocument {escape_turtle(source_file)} ;")
        triples.append(f"    sdhss:extractionMethod {escape_turtle(source_type)} ;")
        triples.append(f"    sdhss:confidence \"{confidence}\"^^xsd:decimal ;")
    
    # Flags
    flags = entity.get('flags', {})
    for flag_key, flag_value in flags.items():
        if isinstance(flag_value, bool) and flag_value:
            triples.append(f"    sdhss:flag_{normalize_to_uri(flag_key)} true ;")
    
    # Remove trailing semicolon and add period
    if triples and triples[-1].endswith(' ;'):
        triples[-1] = triples[-1][:-2] + ' .'
    elif triples and triples[-1].endswith(' .'):
        pass  # Already has period
    else:
        triples.append(' .')
    
    return triples


def generate_header() -> List[str]:
    """Generate Turtle file header with prefixes and metadata."""
    header = [
        PREFIXES.strip(),
        "",
        "# ───────────────────────────────────────────────────────────────────",
        "# People of the Levante — Unified Knowledge Graph",
        "# ───────────────────────────────────────────────────────────────────",
        f"# Generated: {datetime.utcnow().isoformat()}Z",
        "# Ontology: SDHSS (Swiss Data Hub for Social Sciences)",
        "# Format: Turtle (TTL)",
        "# Load into: Apache Jena Fuseki, GraphDB, Virtuoso, etc.",
        "#",
        "# Usage:",
        "#   fuseki-server --mem --update outremer data/unified_kg.ttl",
        "#   curl -X POST 'http://localhost:3030/outremer/query' -d 'query=SELECT...'",
        "# ───────────────────────────────────────────────────────────────────",
        "",
    ]
    return header


# ── Main Pipeline ──────────────────────────────────────────────────────────
def main():
    print(f"📥 Loading knowledge graph from {KG_INPUT}...")
    
    if not KG_INPUT.exists():
        print(f"❌ Error: {KG_INPUT} not found")
        print("   Run: .venv/bin/python3 scripts/build_unified_kg.py first")
        return 1
    
    with open(KG_INPUT, 'r', encoding='utf-8') as f:
        kg_data = json.load(f)
    
    print(f"   Loaded {len(kg_data)} entities")
    
    # Count entity types
    type_counts = {}
    for entity in kg_data.values():
        entity_type = entity.get('type', 'person')
        type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
    
    print(f"   Entity types: {type_counts}")
    
    # Generate triples
    print(f"\n📝 Generating RDF triples...")
    all_triples = generate_header()
    
    person_count = 0
    for entity_id, entity in kg_data.items():
        entity_type = entity.get('type', 'person')
        
        # Currently only handle persons (expand for events, groups, places)
        if entity_type == 'person':
            triples = generate_person_triples(entity)
            all_triples.extend(triples)
            all_triples.append("")  # Blank line between entities
            person_count += 1
    
    # Write output
    print(f"\n💾 Writing {KG_OUTPUT}...")
    KG_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    
    with open(KG_OUTPUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_triples))
    
    file_size = KG_OUTPUT.stat().st_size / (1024 * 1024)  # MB
    print(f"   Written {file_size:.2f} MB")
    
    print(f"\n✅ Done! Generated RDF for {person_count} persons")
    print(f"\n📊 Next steps:")
    print(f"   1. Load into Fuseki:")
    print(f"      fuseki-server --mem --update outremer data/unified_kg.ttl")
    print(f"   2. Query via SPARQL:")
    print(f"      curl -X POST 'http://localhost:3030/outremer/query' \\")
    print(f"           -H 'Content-Type: application/x-www-form-urlencoded' \\")
    print(f"           -d 'query=SELECT * WHERE {{ ?s a sdhss:Person }} LIMIT 10'")
    print(f"   3. Or open web UI: http://localhost:3030/outremer")
    
    return 0


if __name__ == "__main__":
    exit(main())
