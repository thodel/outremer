# Integrated Data Model for Outremer Persons

## Overview

This document describes the unified data model that integrates three person sources:

1. **Outremer Authority File** (`scripts/outremer_index.json`) — 126 curated medieval persons from Omeka XML
2. **Wikidata Peerage Pre-1500** (`scripts/peerage_pre1500_export/`) — ~23,689 persons with birth/death < 1500
3. **Extracted Persons** (`site/data/*.json`) — NER output from pipeline (Gemini + fallback)

## Core Principles

- **Single source of truth per person**: Each person has one canonical record with multiple identifier cross-references
- **Provenance tracking**: Every assertion tracks its source (authority, Wikidata, extraction)
- **Confidence scoring**: Matches between sources have explicit confidence levels
- **Human curation**: All automated matches can be accepted/rejected/flagged by users
- **Extensibility**: New sources (Zotero, VIAF, GND) can be added without schema changes

## Unified Person Schema

```typescript
interface UnifiedPerson {
  // === Canonical Identity ===
  id: string;                    // Internal UUID (e.g., "OUTREMER:person:0001")
  preferred_label: string;       // Primary display name (English, most complete form)
  
  // === Identifiers (cross-source linking) ===
  identifiers: {
    outremer_auth?: string;      // AUTH:CR1, AUTH:CR2, etc.
    wikidata_qid?: string;       // Q1000874
    viaf?: string;
    gnd?: string;
    orcid?: string;              // For modern scholars only
  };
  
  // === Name Variants ===
  names: {
    preferred: string;           // Same as preferred_label
    variants: string[];          // All known spellings/aliases
    normalized: string[];        // Lowercase, accents stripped for matching
  };
  
  // === Biographical Data ===
  bio?: {
    birth?: {
      date?: string;             // ISO 8601 (YYYY-MM-DD or YYYY)
      place?: string;
      wikidata_ref?: string;     // QID of place
    };
    death?: {
      date?: string;
      place?: string;
      wikidata_ref?: string;
    };
    floruit?: {
      start?: string;
      end?: string;
    };
    gender?: "m" | "f" | "unknown";
  };
  
  // === Social/Political Roles ===
  roles: Array<{
    type: string;                // "title", "occupation", "office", "membership"
    label: string;               // "Count of Tripoli", "knight", "member of House of Lords"
    wikidata_ref?: string;       // QID of role/office
    start_date?: string;
    end_date?: string;
    source: "authority" | "wikidata" | "extraction";
  }>;
  
  // === Relationships ===
  relationships: Array<{
    type: string;                // "parent", "child", "spouse", "sibling", "liege", "vassal"
    person_id: string;           // Reference to another UnifiedPerson.id
    person_label: string;
    wikidata_ref?: string;       // QID of related person
    source: "authority" | "wikidata" | "extraction";
  }>;
  
  // === Toponyms (places associated) ===
  places: Array<{
    type: "origin" | "residence" | "title_seat" | "battle";
    label: string;
    wikidata_ref?: string;
  }>;
  
  // === Source Provenance ===
  provenance: {
    sources: Array<{
      type: "authority" | "wikidata" | "extraction";
      source_file?: string;      // e.g., "person/item_149.xml"
      extracted_from_doc?: string; // doc_id if from NER
      confidence?: number;       // 0.0-1.0 for extraction matches
      match_type?: "exact" | "fuzzy" | "manual";
    }>;
    created_at: string;          // ISO 8601
    updated_at: string;
    curated_by?: string;         // Human curator decisions
  };
  
  // === Curation Flags ===
  flags?: {
    not_a_person?: boolean;      // False positive from NER
    wrong_era?: boolean;         // Post-1500 or ancient
    duplicate_of?: string;       // Merged into another person
    needs_review?: boolean;
    rejected_wikidata_matches?: string[]; // QIDs user rejected
    accepted_wikidata_matches?: string[]; // QIDs user accepted
  };
}
```

## Matching Strategy

### Tier 1: Exact/Near-Exact Matches (confidence ≥ 0.9)
- Normalize both names (lowercase, strip accents, remove punctuation)
- Check if normalized forms are identical
- Check if one contains the other + regnal number match
- Example: "Baldwin IV of Jerusalem" ↔ "Baldwin 4 of Jerusalem"

### Tier 2: Fuzzy + Contextual (confidence 0.6–0.9)
- Token overlap ≥ 50% (excluding stopwords)
- Regnal number match OR toponym match
- Phonetic similarity (Soundex/Metaphone) for given names
- Example: "Raymond of Toulouse" ↔ "Raymond IV, Count of Toulouse"

### Tier 3: Weak Candidates (confidence < 0.6)
- Single token match (e.g., "Hugh" → many candidates)
- Requires human review or additional context
- Show in UI but don't auto-link

## File Structure

```
outremer/
├── scripts/
│   ├── outremer_index.json          # Original authority (126 persons)
│   ├── peerage_pre1500_export/      # Wikidata dump (~23k persons)
│   │   ├── qids.csv                 # Master QID list
│   │   ├── data_pages/*.csv         # Full statements per QID
│   │   └── qid_pages/*.csv          # Paginated QID lists
│   ├── build_unified_kg.py          # NEW: Merge all sources
│   └── reconcile_sources.py         # NEW: Run matching algorithms
├── data/
│   ├── unified_kg.json              # NEW: Master knowledge graph
│   ├── decisions.json               # User curation (accept/reject/flags)
│   └── staging/queue.json           # Upload queue
├── site/
│   └── data/
│       ├── authority.json           # Legacy: original authority only
│       ├── wikidata_matches.json    # Legacy: WD reconciliation cache
│       └── *.json                   # Extracted documents
└── docs/
    └── INTEGRATED_DATA_MODEL.md     # This file
```

## Implementation Phases

### Phase 1: Data Loading ✅
- [x] Export Wikidata Peerage pre-1500 (23,689 persons)
- [x] Load Outremer authority (126 persons)
- [ ] Parse all extracted documents

### Phase 2: Matching Engine
- [ ] Implement 3-tier matching algorithm
- [ ] Generate candidate links with confidence scores
- [ ] Write to `data/unified_kg.json`

### Phase 3: Curation UI
- [ ] Update explorer.html to show unified KG
- [ ] Add accept/reject buttons for Wikidata matches
- [ ] Bulk operations for noise filtering

### Phase 4: Pipeline Integration
- [ ] Fix Gemini extraction prompt (reduce bibliographic noise)
- [ ] Post-processing filter for false positives
- [ ] Auto-link high-confidence matches during extraction

## Query Examples

### Find all persons mentioned in a document with Wikidata enrichment
```python
kg = load_unified_kg()
doc = load_doc("rileysmith-motivesearliestcrusaders-1983")
for link in doc['links']:
    person = kg.find_by_name(link['person'])
    if person and person.identifiers.wikidata_qid:
        enrich_with_wikidata(person.identifiers.wikidata_qid)
```

### Export to TEI with standardized persNames
```xml
<persName ref="#AUTH:CR1 #Q1000874">
  <forename>Baldwin</forename>
  <regnal>IV</regnal>
  <settlement>Jerusalem</settlement>
</persName>
```

## Next Steps

1. Build unified KG from all three sources
2. Run matching engine to generate candidate links
3. Filter NER noise with blacklist/whitelist approach
4. Re-run full pipeline with improved prompts + auto-linking
