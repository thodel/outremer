# Knowledge Graph Ingestion Proposal

## Executive Summary

This document proposes a comprehensive solution for ingesting all available data sources into a unified, queryable knowledge graph following the **SDHSS (Swiss Data Hub for Social Sciences) ontology** and **CIDOC-CRM** standards.

**Current State:**
- ✅ 19,085 entities in `unified_kg.json` (persons only)
- ✅ Basic entity resolution (authority file + Wikidata + extracted)
- ✅ Web UI for browsing and adjudication
- ❌ No formal ontology alignment
- ❌ Limited relationship modeling
- ❌ No event/place entity types in KG
- ❌ No SPARQL/RDF endpoint for complex queries

**Target State:**
- ✅ Multi-entity KG (Persons, Groups, Events, Places, Sources)
- ✅ SDHSS/CIDOC-CRM aligned schema
- ✅ Triplestore backend (Apache Jena Fuseki or GraphDB)
- ✅ SPARQL endpoint for complex queries
- ✅ Provenance tracking for all assertions
- ✅ Confidence scoring for uncertain data
- ✅ Incremental ingestion pipeline

---

## 1. Data Sources Inventory

### 1.1 Structured Sources (High Quality)

| Source | Format | Entities | Status | Priority |
|--------|--------|----------|--------|----------|
| **Outremer Authority** | JSON (Omeka) | 126 persons | ✅ Ingested | P0 |
| **Wikidata Peerage pre-1500** | CSV (SPARQL export) | ~23,689 persons | ✅ Ingested | P0 |
| **DHI Crusaders Database** | Web scrape | ~12,000 persons | ⚠️ Sample only | P0 |
| **Foundation for Medieval Genealogy (FMG)** | HTML/XML | ~15,000 persons | ✅ Partial | P1 |

### 1.2 Semi-Structured Sources (Medium Quality)

| Source | Format | Entities | Status | Priority |
|--------|--------|----------|--------|----------|
| **PDF Extractions (Riley-Smith)** | JSON (Gemini) | 163 persons | ✅ Ingested | P1 |
| **PDF Extractions (Munro-Pope)** | JSON (Gemini) | 93 persons | ✅ Ingested | P1 |
| **Additional PDFs** | PDF | TBD | ⏳ Pending | P2 |

### 1.3 Unstructured Sources (Low Quality)

| Source | Format | Entities | Status | Priority |
|--------|--------|----------|--------|----------|
| **Chronicle texts** | Plain text | TBD | ⏳ Not started | P3 |
| **Charter transcriptions** | TEI-XML | TBD | ⏳ Not started | P3 |

---

## 2. Target Schema (SDHSS Ontology)

### 2.1 Core Entity Types

```turtle
# SDHSS Core Classes
sdhss:Person      a rdfs:Class ;  # Individual humans
sdhss:Group       a rdfs:Class ;  # Collectives (armies, orders, families)
sdhss:Event       a rdfs:Class ;  # Historical events (battles, councils, crusades)
sdhss:Place       a rdfs:Class ;  # Locations (cities, regions, buildings)
sdhss:Source      a rdfs:Class ;  # Documents, manuscripts, databases
sdhss:Role        a rdfs:Class ;  # Functions/positions held
```

### 2.2 Key Properties

```turtle
# Identity & Naming
sdhss:preferredLabel    rdfs:domain sdhss:Person ; rdfs:range xsd:string .
sdhss:variantName       rdfs:domain sdhss:Person ; rdfs:range xsd:string .
sdhss:normalizedForm    rdfs:domain sdhss:Person ; rdfs:range xsd:string .

# Biographical Data
sdhss:birthDate         rdfs:domain sdhss:Person ; rdfs:range xsd:gYear .
sdhss:deathDate         rdfs:domain sdhss:Person ; rdfs:range xsd:gYear .
sdhss:floruit           rdfs:domain sdhss:Person ; rdfs:range xsd:gYear .
sdhss:gender            rdfs:domain sdhss:Person ; rdfs:range sdhss:Gender .

# Relationships (Person-Person)
sdhss:parentOf          rdfs:domain sdhss:Person ; rdfs:range sdhss:Person .
sdhss:childOf           rdfs:domain sdhss:Person ; rdfs:range sdhss:Person .
sdhss:spouseOf          rdfs:domain sdhss:Person ; rdfs:range sdhss:Person .
sdhss:siblingOf         rdfs:domain sdhss:Person ; rdfs:range sdhss:Person .
sdhss:liegeOf           rdfs:domain sdhss:Person ; rdfs:range sdhss:Person .
sdhss:vassalOf          rdfs:domain sdhss:Person ; rdfs:range sdhss:Person .

# Participation (Person-Event)
sdhss:participatedIn    rdfs:domain sdhss:Person ; rdfs:range sdhss:Event .
sdhss:roleInEvent       rdfs:domain sdhss:Participation ; rdfs:range xsd:string .
sdhss:outcome           rdfs:domain sdhss:Participation ; rdfs:range xsd:string .

# Location (Person-Place, Event-Place)
sdhss:bornIn            rdfs:domain sdhss:Person ; rdfs:range sdhss:Place .
sdhss:diedIn            rdfs:domain sdhss:Person ; rdfs:range sdhss:Place .
sdhss:residedIn         rdfs:domain sdhss:Person ; rdfs:range sdhss:Place .
sdhss:locatedAt         rdfs:domain sdhss:Event ; rdfs:range sdhss:Place .

# Group Membership
sdhss:memberOf          rdfs:domain sdhss:Person ; rdfs:range sdhss:Group .
sdhss:groupType         rdfs:domain sdhss:Group ; rdfs:range xsd:string .

# Provenance & Confidence
sdhss:sourceDocument    rdfs:domain sdhss:Assertion ; rdfs:range sdhss:Source .
sdhss:confidence        rdfs:domain sdhss:Assertion ; rdfs:range xsd:decimal .
sdhss:extractionMethod  rdfs:domain sdhss:Assertion ; rdfs:range xsd:string .
```

### 2.3 Example RDF Triples

```turtle
# Person with multiple names
ex:AUTH:CR1  a  sdhss:Person ;
    sdhss:preferredLabel  "Conrad III of Germany" ;
    sdhss:variantName     "Conrad III", "Conrad de Alemania" ;
    sdhss:normalizedForm  "conrad iii of germany" ;
    sdhss:birthDate       "1093"^^xsd:gYear ;
    sdhss:deathDate       "1152"^^xsd:gYear ;
    sdhss:gender          sdhss:Male ;
    sdhss:memberOf        ex:GROUP:HolyRomanEmpire ;
    sdhss:participatedIn  ex:EVENT:SecondCrusade ;
    sdhss:residedIn       ex:PLACE:Germany .

# Event with participants
ex:EVENT:SecondCrusade  a  sdhss:Event ;
    sdhss:preferredLabel  "Second Crusade" ;
    sdhss:startDate       "1147"^^xsd:gYear ;
    sdhss:endDate         "1149"^^xsd:gYear ;
    sdhss:locatedAt       ex:PLACE:Levant, ex:PLACE:Anatolia ;
    sdhss:participant     ex:AUTH:CR1, ex:AUTH:LOU7 .

# Assertion with provenance
ex:ASSERT:birth_conrad  a  sdhss:Assertion ;
    sdhss:subject         ex:AUTH:CR1 ;
    sdhss:property        sdhss:birthDate ;
    sdhss:value           "1093"^^xsd:gYear ;
    sdhss:sourceDocument  ex:SOURCE:Wikidata_Q164293 ;
    sdhss:confidence      "0.85"^^xsd:decimal ;
    sdhss:extractionMethod  "wikidata_import" .
```

---

## 3. Ingestion Architecture

### 3.1 Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Authority│  │ Wikidata │  │   DHI    │  │   FMG    │        │
│  │  (JSON)  │  │  (CSV)   │  │ (Scrape) │  │  (XML)   │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │             │             │             │               │
│       └─────────────┴─────────────┴─────────────┘               │
│                         │                                        │
│                         ▼                                        │
│              ┌─────────────────────┐                            │
│              │  Normalization Layer │                            │
│              │  - Name standardization                         │
│              │  - Date parsing (ISO 8601)                      │
│              │  - Place geocoding                              │
│              └──────────┬──────────┘                            │
│                         │                                        │
│                         ▼                                        │
│              ┌─────────────────────┐                            │
│              │  Entity Resolution   │                            │
│              │  - Deduplication     │                            │
│              │  - Confidence scoring                            │
│              │  - Merge candidates  │                            │
│              └──────────┬──────────┘                            │
│                         │                                        │
│                         ▼                                        │
│              ┌─────────────────────┐                            │
│              │  SDHSS Mapping      │                            │
│              │  - RDF triple gen   │                            │
│              │  - Ontology align   │                            │
│              │  - Provenance track │                            │
│              └──────────┬──────────┘                            │
│                         │                                        │
│                         ▼                                        │
│              ┌─────────────────────┐                            │
│              │   Triplestore       │                            │
│              │  (Fuseki / GraphDB) │                            │
│              │  - SPARQL endpoint  │                            │
│              │  - Web UI           │                            │
│              └─────────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Component Details

#### A. Normalization Layer (`scripts/normalize/`)

```python
# scripts/normalize/names.py
def normalize_name(name: str) -> str:
    """Standardize name format for matching."""
    # Lowercase, strip accents, remove punctuation
    # Handle patronymics, toponyms, regnal numbers
    
# scripts/normalize/dates.py
def parse_date(date_str: str) -> Optional[dict]:
    """Parse various date formats to ISO 8601."""
    # Handle: "12th century", "fl. 1145-1152", "d. 1099"
    # Return: {"type": "exact|approx|floruit", "value": "1145", ...}

# scripts/normalize/places.py
def geocode_place(place_name: str) -> Optional[dict]:
    """Resolve place names to coordinates + Wikidata QID."""
    # Use Geonames API + Wikidata SPARQL
    # Return: {"qid": "Q1234", "lat": 31.7, "lon": 35.2, ...}
```

#### B. Entity Resolution (`scripts/resolve/`)

```python
# scripts/resolve/matcher.py
class EntityResolver:
    """Match and merge entities from different sources."""
    
    def match(self, person_a: dict, person_b: dict) -> float:
        """Return confidence score 0.0-1.0 for match."""
        # Name similarity (Levenshtein, Jaro-Winkler)
        # Date overlap (birth/death ranges)
        # Relationship overlap (same parents/spouses)
        # Place overlap (same birthplace/residence)
        
    def merge(self, entities: List[dict]) -> dict:
        """Merge multiple entity records into one."""
        # Keep highest-confidence values
        # Preserve all provenance information
        # Track merge history
```

#### C. SDHSS Mapping (`scripts/mapping/`)

```python
# scripts/mapping/to_rdf.py
class SDHSSMapper:
    """Convert internal KG format to SDHSS RDF triples."""
    
    def map_person(self, entity: dict) -> List[Tuple]:
        """Generate RDF triples for a person entity."""
        triples = []
        triples.append((entity['id'], RDF.type, SDHSS.Person))
        triples.append((entity['id'], SDHSS.preferredLabel, entity['label']))
        # ... more triples
        return triples
    
    def map_event(self, entity: dict) -> List[Tuple]:
        """Generate RDF triples for an event."""
        # Similar pattern for events, groups, places
```

#### D. Triplestore Backend (`scripts/store/`)

```python
# scripts/store/fuseki.py
class FusekiStore:
    """Apache Jena Fuseki triplestore connector."""
    
    def __init__(self, endpoint: str, dataset: str):
        self.endpoint = endpoint
        self.dataset = dataset
        
    def load_triples(self, triples: List[Tuple], format: str = "turtle"):
        """Bulk load triples into triplestore."""
        
    def sparql_query(self, query: str) -> List[dict]:
        """Execute SPARQL query, return results as dicts."""
        
    def update(self, update_query: str):
        """Execute SPARQL UPDATE query."""
```

---

## 4. Implementation Plan

### Phase 1: Foundation (2-3 weeks)

**Goal:** Set up triplestore infrastructure and basic ingestion pipeline

- [ ] **Week 1: Infrastructure**
  - [ ] Install Apache Jena Fuseki on VM
  - [ ] Configure Caddy reverse proxy (SPARQL endpoint)
  - [ ] Create dataset: `outremer-kg`
  - [ ] Set up backup strategy (daily dumps)
  
- [ ] **Week 2: Schema & Mapping**
  - [ ] Define SDHSS ontology (TTL file)
  - [ ] Create Python RDF mapper
  - [ ] Test with authority file (126 persons)
  - [ ] Validate triples with SHACL shapes

- [ ] **Week 3: Basic Ingestion**
  - [ ] Ingest Wikidata Peerage (23K persons)
  - [ ] Run entity resolution
  - [ ] Load into Fuseki
  - [ ] Test SPARQL queries

**Deliverables:**
- Working SPARQL endpoint at `https://hodelweb.ch/sparql`
- 24K+ persons in triplestore
- Basic queries working

### Phase 2: Enrichment (3-4 weeks)

**Goal:** Add events, groups, places; improve relationships

- [ ] **Week 4-5: Event Extraction**
  - [ ] Define event schema (battles, councils, crusades)
  - [ ] Extract events from PDFs (Gemini prompt)
  - [ ] Link persons to events (participation)
  - [ ] Add temporal data (start/end dates)

- [ ] **Week 6: Group Extraction**
  - [ ] Define group schema (military orders, families, armies)
  - [ ] Extract groups from texts
  - [ ] Link persons to groups (membership)
  - [ ] Handle collective entities properly

- [ ] **Week 7: Place Resolution**
  - [ ] Geocode all place names (Geonames API)
  - [ ] Link to Wikidata places
  - [ ] Add hierarchical structure (city → region → country)
  - [ ] Map medieval toponyms to modern locations

**Deliverables:**
- Events, Groups, Places entities
- Rich relationship network
- Geographic visualization possible

### Phase 3: Advanced Features (3-4 weeks)

**Goal:** Provenance, confidence, incremental updates

- [ ] **Week 8-9: Provenance Tracking**
  - [ ] Model all assertions with provenance
  - [ ] Track source, method, confidence
  - [ ] Support conflicting claims
  - [ ] Enable "trust but verify" workflow

- [ ] **Week 10: Incremental Ingestion**
  - [ ] Design delta-update mechanism
  - [ ] Handle new PDFs automatically
  - [ ] Reconcile against existing entities
  - [ ] Update confidence scores

- [ ] **Week 11: Web UI Integration**
  - [ ] SPARQL query builder in explorer.html
  - [ ] Graph visualization (D3.js force-directed)
  - [ ] Timeline view for events
  - [ ] Map view for places

**Deliverables:**
- Full provenance tracking
- Automated pipeline for new data
- Rich web interface

---

## 5. Technical Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Triplestore** | Apache Jena Fuseki | Open source, SPARQL 1.1, easy deployment |
| **Alternative** | GraphDB Free | Better UI, reasoning, but more complex |
| **RDF Library** | rdflib (Python) | Mature, good SPARQL support |
| **Alternative** | RDFLib + SPARQLWrapper | More flexible querying |
| **Geocoding** | Geonames API + Wikidata | Free tier sufficient, good coverage |
| **Name Matching** | rapidfuzz (Python) | Fast, accurate string similarity |
| **Date Parsing** | dateparser (Python) | Handles historical date formats |
| **Visualization** | D3.js + Leaflet | Flexible, well-documented |
| **Deployment** | Docker + systemd | Reproducible, easy maintenance |

---

## 6. Example SPARQL Queries

### 6.1 Find All Participants in Second Crusade

```sparql
PREFIX sdhss: <http://sdhss.ch/ontology#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?person ?personLabel ?role ?outcome
WHERE {
  ?event a sdhss:Event ;
         sdhss:preferredLabel "Second Crusade" ;
         sdhss:startDate ?start .
  
  ?participation sdhss:event ?event ;
                 sdhss:participant ?person ;
                 sdhss:roleInEvent ?role .
  
  OPTIONAL { ?participation sdhss:outcome ?outcome }
  
  ?person sdhss:preferredLabel ?personLabel .
  
  FILTER (?start >= "1147"^^xsd:gYear && ?start <= "1149"^^xsd:gYear)
}
ORDER BY ?personLabel
```

### 6.2 Find All Templars with Birth/Death Dates

```sparql
PREFIX sdhss: <http://sdhss.ch/ontology#>

SELECT ?person ?personLabel ?birth ?death
WHERE {
  ?templar a sdhss:Group ;
           sdhss:preferredLabel "Knights Templar" .
  
  ?person sdhss:memberOf ?templar ;
          sdhss:preferredLabel ?personLabel .
  
  OPTIONAL { ?person sdhss:birthDate ?birth }
  OPTIONAL { ?person sdhss:deathDate ?death }
}
ORDER BY ?birth
```

### 6.3 Network Query: Find All Relatives of Baldwin IV

```sparql
PREFIX sdhss: <http://sdhss.ch/ontology#>

SELECT ?relative ?relativeLabel ?relationshipType
WHERE {
  ?baldwin a sdhss:Person ;
           sdhss:preferredLabel "Baldwin IV of Jerusalem" .
  
  {
    ?baldwin sdhss:parentOf ?relative .
    BIND("child" AS ?relationshipType)
  } UNION {
    ?relative sdhss:parentOf ?baldwin .
    BIND("parent" AS ?relationshipType)
  } UNION {
    ?baldwin sdhss:siblingOf ?relative .
    BIND("sibling" AS ?relationshipType)
  } UNION {
    ?baldwin sdhss:spouseOf ?relative .
    BIND("spouse" AS ?relationshipType)
  }
  
  ?relative sdhss:preferredLabel ?relativeLabel .
}
```

### 6.4 Temporal Query: Persons Active During Specific Period

```sparql
PREFIX sdhss: <http://sdhss.ch/ontology#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?person ?personLabel ?floruit
WHERE {
  ?person a sdhss:Person ;
          sdhss:preferredLabel ?personLabel ;
          sdhss:floruit ?floruit .
  
  # Persons active between 1150 and 1200
  FILTER (?floruit >= "1150"^^xsd:gYear && ?floruit <= "1200"^^xsd:gYear)
}
ORDER BY ?floruit
LIMIT 100
```

---

## 7. Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Data quality issues** | High | Medium | Confidence scoring, provenance tracking, manual review UI |
| **Entity resolution errors** | High | Medium | Human-in-the-loop adjudication, conservative merging |
| **Performance degradation** | Medium | Low | Indexing, query optimization, pagination |
| **Ontology mismatch** | Medium | Low | Iterative refinement, community feedback |
| **Bot protection (DHI)** | Low | High | Manual export request, alternative sources |

---

## 8. Success Metrics

| Metric | Current | Target (Phase 1) | Target (Phase 3) |
|--------|---------|------------------|------------------|
| **Entities** | 19K persons | 25K persons | 50K+ (multi-type) |
| **Relationships** | ~100 | 1,000+ | 10,000+ |
| **Query latency** | N/A (JSON) | <500ms | <200ms |
| **Data sources** | 4 | 6 | 10+ |
| **SPARQL queries** | 0 | 10+ | 50+ |
| **User interactions** | 11 decisions | 100+ | 1,000+ |

---

## 9. Next Steps

1. **Review this proposal** with Tobias (feedback on priorities, scope)
2. **Set up Fuseki** on VM (install, configure, test)
3. **Create SDHSS ontology** (TTL file with core classes/properties)
4. **Build ingestion script** (authority file → RDF → Fuseki)
5. **Test with sample data** (126 authority persons)
6. **Scale to full dataset** (Wikidata Peerage + DHI + FMG)
7. **Build SPARQL UI** (query builder + results visualization)

---

## Appendix A: Existing Scripts to Reuse

- `scripts/build_unified_kg.py` — Current KG builder (adapt for RDF output)
- `scripts/wikidata_reconcile.py` — Wikidata matching (keep as-is)
- `scripts/extract_persons_google.py` — PDF extraction (keep as-is)
- `scripts/scrape_dhi_crusaders.py` — DHI scraper (adapt for full export)

## Appendix B: Recommended Reading

- **SDHSS Ontology:** https://sdhss.ch/ontology
- **CIDOC-CRM:** http://www.cidoc-crm.org/
- **Apache Jena:** https://jena.apache.org/
- **SPARQL 1.1:** https://www.w3.org/TR/sparql11-query/
- **SHACL Validation:** https://www.w3.org/TR/shacl/

---

**Document Version:** 1.0  
**Date:** 2026-02-27  
**Author:** cl-bot (with Tobias Hodel)
