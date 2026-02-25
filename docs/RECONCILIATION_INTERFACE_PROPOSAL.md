# Outremer Reconciliation Interface & SDHSS Migration Proposal

**Date:** 2026-02-25  
**Author:** cl-bot (based on Tobias Hodel's requirements)

---

## Executive Summary

This document proposes:

1. **A new "Reconcile" section** on the Outremer website for community-driven dataset reconciliation
2. **Migration to SDHSS ontology** (CIDOC CRM extension for humanities) for semantic interoperability
3. **Open-source infrastructure** that runs on the current VM (194.13.80.183)

---

## Part 1: "Contribute Your Knowledge → Reconcile Datasets" Interface

### 🎯 Purpose

Allow scholars to review, validate, and merge person records from different sources:
- **Outremer Authority File** (126 curated persons)
- **Wikidata Peerage** (18,349 persons)
- **FMG MedLands** (628 newly extracted persons)
- **Riley-Smith extraction** (~400 persons)
- **Munro-Popes extraction** (~200 persons)

### 📐 Proposed UI Structure

```
/outremer/reconcile/
├── Dashboard
│   ├── Statistics (total persons, matches, conflicts)
│   ├── Recent activity feed
│   └── Your contributions
│
├── Review Queue
│   ├── Needs Review (610 persons flagged during KG build)
│   ├── Conflicts (same person, different data)
│   ├── Duplicates (potential matches)
│   └── My Reviews (user's history)
│
├── Search & Compare
│   ├── Multi-person search
│   ├── Side-by-side comparison view
│   └── Merge/split tools
│
└── Export
    ├── Download reconciled datasets
    ├── SPARQL queries
    └── RDF/TTL exports
```

### 🔧 Key Features

#### 1. **Person Card View**

Each person shows:
- **Name & variants** (from all sources)
- **Dates** (birth, death, floruit) with confidence indicators
- **Roles/Titles** (tagged by source)
- **Relations** (family, social, political)
- **Sources** (color-coded: 🟢 Authority | 🟠 Wikidata | 🔵 FMG | 🟣 Riley-Smith)
- **Confidence score** (auto-calculated from agreement between sources)

#### 2. **Matching Interface**

When potential duplicates are detected:

```
┌─────────────────────────────────┬─────────────────────────────────┐
│  Person A (Authority:AUTH:CR1)  │  Person B (FMG:0042)            │
├─────────────────────────────────┼─────────────────────────────────┤
│  Baldwin I of Jerusalem         │  BAUDOUIN I de Boulogne         │
│  King of Jerusalem (1100-1118)  │  King of Jerusalem (fl. 1100)   │
│  ✓ Wikidata: Q30578             │  ✗ No Wikidata link             │
│  Relations: 12                  │  Relations: 8                   │
│  Sources: 3                     │  Sources: 1                     │
└─────────────────────────────────┴─────────────────────────────────┘

[✓] These are the SAME PERSON → MERGE
[✗] These are DIFFERENT people
[?] Mark as CONFLICT (needs expert review)

Merge preview:
- Combined name: "Baldwin I of Jerusalem" (preferred)
  Variants: ["BAUDOUIN I de Boulogne", "Baldwin I"]
- Combined relations: 15 unique (5 duplicates removed)
- Confidence: HIGH (name match + title match + date overlap)
```

#### 3. **Batch Operations**

For power users:
- **Bulk approve** (e.g., "Approve all FMG→Wikidata matches with >90% confidence")
- **Filter by source** ("Show me only FMG entries without Wikidata links")
- **Export filtered sets** ("Download all 'needs review' persons as CSV")

#### 4. **Gamification & Attribution**

- **User profiles**: Track contributions (reviews, merges, corrections)
- **Badges**: "100 reviews", "Expert curator", "Conflict resolver"
- **ORCID integration**: Attribute scholarly work
- **Citation export**: Generate citations for dataset contributions

### 💻 Technical Implementation

#### Frontend Stack

```yaml
Framework: React 18+ (or Vue 3)
UI Library: Material-UI or Tailwind CSS
State: Redux Toolkit / Zustand
Data Viz: D3.js or Recharts
SPARQL Editor: YASQE (from Yasgui)
```

#### Backend Stack

```yaml
API: FastAPI (Python) or Express (Node.js)
Database: PostgreSQL + pg_trgm (fuzzy search)
Search: Elasticsearch (optional, for large-scale)
Auth: OAuth2 (Google, GitHub, ORCID)
Task Queue: Celery + Redis (for background matching)
```

#### Matching Algorithm

```python
# Pseudo-code for person matching
def calculate_match_score(person_a, person_b):
    score = 0
    
    # Name similarity (Levenshtein + token sort)
    name_score = fuzzy_ratio(a.name, b.name)  # 0-100
    score += name_score * 0.4  # 40% weight
    
    # Date overlap
    if dates_overlap(a.dates, b.dates):
        score += 25
    
    # Title/role similarity
    title_score = jaccard(a.roles, b.roles)
    score += title_score * 20
    
    # Shared relations (very strong signal)
    shared_rels = count_shared_relations(a.relations, b.relations)
    score += min(shared_rels * 5, 15)
    
    # Same Wikidata QID (instant high confidence)
    if a.wikidata_qid and a.wikidata_qid == b.wikidata_qid:
        score = 95
    
    return score

# Thresholds:
# >= 85: Auto-suggest merge
# 60-84: Flag for review
# < 60: No match
```

### 📊 Data Model for Reconciliation

```typescript
interface ReconciliationRecord {
  id: string;  // UUID
  status: 'pending' | 'approved' | 'rejected' | 'conflict';
  
  // The persons being compared
  candidates: {
    person_id: string;
    source: 'authority' | 'wikidata' | 'fmg' | 'riley-smith';
    confidence: number;  // 0-100
  }[];
  
  // User decisions
  reviews: {
    user_id: string;
    decision: 'merge' | 'split' | 'conflict';
    comment?: string;
    timestamp: ISO8601;
  }[];
  
  // Final outcome
  result?: {
    merged_into: string;  // person_id
    merged_at: ISO8601;
    merged_by: string;  // user_id
  };
}
```

---

## Part 2: SDHSS Ontology Migration

### 📚 What is SDHSS?

**SDHSS** (Semantic Data for Humanities and Social Sciences) is an extension of **CIDOC CRM** designed specifically for historical research.

**Key features:**
- Built on CIDOC CRM (ISO 21127:2014)
- Models **historical epistemic distance** (distinguishes researcher's concepts from historical reality)
- Supports **social representations** and **collective intentionality**
- Used by LOD4HSS projects (Linked Open Data for Humanities & Social Sciences)

**Ontome namespace:** https://ontome.net/namespace/11

### 🏗️ Why Migrate to SDHSS?

| Current Approach | SDHSS Approach |
|------------------|----------------|
| Custom JSON schema | Standard ontology (interoperable) |
| Limited relations | Rich property graph (100+ properties) |
| No temporal reasoning | Native time modeling (CRM:E52 Time-Span) |
| Flat structure | Hierarchical classes with inheritance |
| Proprietary format | RDF/OWL (FAIR principles) |
| Hard to query | SPARQL support |

### 🔄 Mapping Current Data to SDHSS

#### Current Outremer Format

```json
{
  "id": "AUTH:CR1",
  "name": {"label": "Baldwin I of Jerusalem"},
  "dates": {"birth": "1058", "death": "1118"},
  "roles": ["King of Jerusalem"],
  "relations": [
    {"type": "child_of", "name": "Eustace II of Boulogne"}
  ]
}
```

#### SDHSS/RDF Equivalent

```turtle
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix sdhss: <https://sdhss.org/ontology/core/> .
@prefix outremer: <https://thodel.github.io/outremer/data/> .

outremer:AUTH_CR1 a 
    crm:E21_Person,
    sdhss:H1_Historical_Actor ;
    
    crm:P1_is_identified_by 
        [ a crm:E41_Appellation ;
          crm:P190_has_symbolic_content "Baldwin I of Jerusalem" ] ;
    
    crm:P98i_was_born 
        [ a crm:E67_Birth ;
          crm:P4_has_time-span 
            [ a crm:E52_Time-Span ;
              crm:P82a_begin_of_the_begin "1058"^^xsd:gYear ] ] ;
    
    crm:P99i_died 
        [ a crm:E69_Death ;
          crm:P4_has_time-span 
            [ a crm:E52_Time-Span ;
              crm:P82b_end_of_the_end "1118"^^xsd:gYear ] ] ;
    
    crm:P14_carried_out 
        [ a crm:E7_Activity ;
          crm:P14i_performed_by outremer:AUTH_CR1 ;
          crm:P2_has_type 
            [ a crm:E55_Type ;
              skos:prefLabel "King of Jerusalem" ] ] ;
    
    sdhss:P1_is_child_of outremer:AUTH_Eustace_II ;
    
    crm:P129_is_about 
        [ a sdhss:S1_Social_Representation ;
          sdhss:P1_refers_to "Kingship of Jerusalem (12th century)" ] .
```

### 🛠️ Migration Strategy

#### Phase 1: Ontology Setup (Week 1-2)

1. **Install Ontome-compatible triplestore** (see infrastructure below)
2. **Download SDHSS ontology** (OWL/RDF format from Ontome)
3. **Create mapping document** (current JSON → SDHSS classes/properties)
4. **Set up SHACL shapes** (data validation rules)

#### Phase 2: Data Transformation (Week 2-3)

1. **Write conversion scripts** (Python + rdflib)
2. **Transform existing KG** (19,085 persons → RDF)
3. **Validate with SHACL** (ensure ontological consistency)
4. **Load into triplestore**

#### Phase 3: Query Layer (Week 3-4)

1. **Build SPARQL endpoint** (public read access)
2. **Create example queries** (common research questions)
3. **Integrate with frontend** (new "Query" page)
4. **Documentation** (tutorial for historians)

### 📝 Key SDHSS Classes for Outremer

```
sdhss:H1_Historical_Actor (extends crm:E21_Person)
  ├─ sdhss:H2_Group (families, dynasties, orders)
  └─ sdhss:H3_Role (kingship, counts, etc.)

crm:E5_Event (crusades, battles, councils)
  ├─ crm:E7_Activity (travel, writing, ruling)
  └─ crm:E9_Move (movement between places)

crm:E53_Place (Jerusalem, Antioch, European origins)
  └─ sdhss:S5_Historical_Place (with temporal bounds)

crm:E52_Time-Span (reign periods, lifespans)
  └─ crm:E61_Time Primitive (dates with uncertainty)

sdhss:S1_Social_Representation (concepts like "knighthood", "pilgrimage")
  └─ crm:E55_Type (typed using controlled vocabularies)
```

---

## Part 3: Open Source Infrastructure (VM-Compatible)

### 🖥️ Current VM Specs

- **Host:** 194.13.80.183 (Ubuntu 24.04.1 LTS)
- **RAM:** Assumed 4-8 GB (typical for this tier)
- **Storage:** Assumed 80-160 GB SSD
- **Services:** Caddy, Flask, Nextcloud, Python 3.x

### ✅ Recommended Stack (All Open Source)

#### Option A: GraphDB Free Edition (Recommended)

```yaml
Software: GraphDB Free 10.x
License: Proprietary but free (up to 50M triples)
RAM: 2-4 GB
Storage: ~10 GB for Outremer KG

Features:
  ✓ SPARQL 1.1 endpoint
  ✓ SHACL validation
  ✓ Full-text search
  ✓ Web-based Workbench UI
  ✓ REST API
  ✗ No clustering (Free version limitation)

Installation:
  wget http://graphdb.ontotext.com/download/graphdb-free-10.x.zip
  unzip graphdb-free-10.x.zip
  cd graphdb-free-10.x/bin
  ./graphdb
```

**Pros:**
- Best-in-class performance
- Excellent documentation
- Visual graph explorer
- Easy backup/restore

**Cons:**
- Not fully open source (free but proprietary)
- 50M triple limit (should be sufficient for ~100K persons)

---

#### Option B: Apache Jena Fuseki (Fully Open Source)

```yaml
Software: Apache Jena Fuseki 4.x
License: Apache 2.0 (fully open source)
RAM: 1-2 GB
Storage: ~10 GB

Features:
  ✓ SPARQL 1.1 endpoint
  ✓ REST API
  ✓ Web UI (basic)
  ✓ TDB2 storage (scalable)
  ✗ No built-in SHACL (requires add-on)
  ✗ Basic full-text search

Installation:
  wget https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-4.x.tar.gz
  tar xzf apache-jena-fuseki-4.x.tar.gz
  cd apache-jena-fuseki-4.x
  ./fuseki-server --mem /outremer
```

**Pros:**
- Fully open source (Apache License)
- Lightweight
- Mature project (20+ years)
- Good Java ecosystem integration

**Cons:**
- Less user-friendly than GraphDB
- Requires manual SHACL setup
- Basic UI

---

#### Option C: Blazegraph (High Performance)

```yaml
Software: Blazegraph 2.x
License: GPL 3.0 (open source)
RAM: 2-4 GB
Storage: ~10 GB

Features:
  ✓ SPARQL 1.1 endpoint
  ✓ High-performance (used by Wikidata!)
  ✓ Full-text search (Lucene)
  ✓ REST API
  ✗ Complex setup
  ✗ No native SHACL

Installation:
  wget https://github.com/blazegraph/database/releases/download/BLAZEGRAPH_RELEASE_2_1_6/blazegraph.jar
  java -server -Xmx4G -jar blazegraph.jar
```

**Pros:**
- Powers Wikidata (proven at scale)
- Very fast
- Advanced indexing

**Cons:**
- Steep learning curve
- GPL license (viral)
- Less documentation

---

### 🏆 Recommendation: **GraphDB Free**

For your use case, I recommend **GraphDB Free** because:

1. **Fits VM specs** (runs comfortably on 4 GB RAM)
2. **Excellent UI** (scholars can explore without SPARQL knowledge)
3. **Built-in SHACL** (validates SDHSS compliance)
4. **Easy maintenance** (single binary, simple backups)
5. **Free for academic use** (no cost barrier)

The 50M triple limit is not a concern:
- Current KG: ~19K persons × ~50 triples/person ≈ **1M triples**
- Even with 10× growth: **10M triples** (well under limit)

---

### 📦 Complete Infrastructure Setup

```bash
#!/bin/bash
# install-outremer-graph.sh
# Run on VM: ssh th@194.13.80.183

set -e

echo "=== Installing Outremer Graph Infrastructure ==="

# 1. Install GraphDB
cd /opt
sudo wget http://graphdb.ontotext.com/download/graphdb-free-10.7.0.zip
sudo unzip graphdb-free-10.7.0.zip
sudo ln -s graphdb-free-10.7.0 graphdb
sudo chown -R th:th graphdb

# 2. Create systemd service
cat <<EOF | sudo tee /etc/systemd/system/graphdb.service
[Unit]
Description=GraphDB Triplestore
After=network.target

[Service]
Type=forking
User=th
ExecStart=/opt/graphdb/bin/graphdb start
ExecStop=/opt/graphdb/bin/graphdb stop
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable graphdb
sudo systemctl start graphdb

# 3. Configure Caddy reverse proxy
cat <<EOF | sudo tee -a /etc/caddy/Caddyfile

# GraphDB SPARQL endpoint
sparql.hodelweb.ch {
    reverse_proxy localhost:7200
}
EOF

sudo systemctl restart caddy

# 4. Create data directories
mkdir -p ~/outremer-graph/{data,backup,scripts}

# 5. Download SDHSS ontology
cd ~/outremer-graph
wget https://ontome.net/ontology/export/11 -O sdhss-core.owl

# 6. Initial setup instructions
cat <<EOF

✅ Installation complete!

Next steps:
1. Visit http://194.13.80.183:7200 (GraphDB Workbench)
2. Create repository "outremer"
3. Upload SDHSS ontology: ~/outremer-graph/sdhss-core.owl
4. Transform and load Outremer KG (see docs/SDHSS_MIGRATION.md)

SPARQL endpoint: https://sparql.hodelweb.ch/outremer/sparkql
(once DNS is configured)

EOF
```

---

### 🔄 Data Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Authority│  │ Wikidata │  │   FMG    │  │  Riley-  │   │
│  │   (126)  │  │ (18,349) │  │  (628)   │  │  Smith   │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
└───────┼─────────────┼─────────────┼─────────────┼──────────┘
        │             │             │             │
        └─────────────┴─────────────┴─────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  build_unified_kg.py  │
              │  (matching engine)    │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   unified_kg.json     │
              │   (19,085 persons)    │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  convert_to_sdhss.py  │
              │  (JSON → RDF/Turtle)  │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   SHACL Validation    │
              │  (sdhss-shapes.ttl)   │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │      GraphDB Free     │
              │   (SDHSS-compliant)   │
              └───────────┬───────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ SPARQL       │  │ Reconciliation│  │ Public       │
│ Endpoint     │  │ Interface     │  │ Website      │
│ (query)      │  │ (review)      │  │ (browse)     │
└──────────────┘  └──────────────┘  └──────────────┘
```

---

## Part 4: Implementation Timeline

### Phase 1: Foundation (Weeks 1-2)

- [ ] Install GraphDB on VM
- [ ] Configure Caddy reverse proxy
- [ ] Download SDHSS ontology
- [ ] Create JSON→RDF conversion script
- [ ] Test with small subset (100 persons)

### Phase 2: Migration (Weeks 2-3)

- [ ] Convert full KG (19,085 persons → RDF)
- [ ] Validate with SHACL shapes
- [ ] Load into GraphDB
- [ ] Write example SPARQL queries
- [ ] Performance tuning

### Phase 3: Reconciliation UI (Weeks 3-6)

- [ ] Set up React/Vue frontend
- [ ] Build backend API (FastAPI)
- [ ] Implement matching algorithm
- [ ] Create review interface
- [ ] Add user authentication
- [ ] Beta testing with small group

### Phase 4: Launch (Weeks 6-8)

- [ ] Deploy to production
- [ ] Documentation (user guide, tutorials)
- [ ] Community outreach (DH mailing lists)
- [ ] Monitor and iterate

---

## Part 5: Cost Estimate

| Item | Cost | Notes |
|------|------|-------|
| **Infrastructure** | CHF 0 | Uses existing VM |
| **GraphDB Free** | CHF 0 | Free edition (academic use) |
| **Domain/DNS** | CHF 0 | hodelweb.ch already owned |
| **Development** | CHF 0-500 | Optional: student assistant hours |
| **Total** | **CHF 0-500** | One-time setup cost |

**Ongoing costs:** None (all open source, runs on existing infrastructure)

---

## Part 6: Success Metrics

### Quantitative

- **Persons reconciled**: Target 500+ in first 3 months
- **Community contributors**: Target 10+ active reviewers
- **SPARQL queries/month**: Target 100+ (research usage)
- **Dataset downloads**: Target 50+/month

### Qualitative

- Scholar feedback (surveys, interviews)
- Citations in DH publications
- Integration with other DH projects
- Adoption by other medieval studies initiatives

---

## Appendix A: Example SPARQL Queries

### Query 1: Find All Kings of Jerusalem

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX sdhss: <https://sdhss.org/ontology/core/>

SELECT ?person ?name ?start ?end
WHERE {
  ?person a crm:E21_Person ;
          crm:P1_is_identified_by/crm:P190_has_symbolic_content ?name ;
          crm:P14_carried_out ?activity .
  
  ?activity crm:P2_has_type ?type .
  FILTER(CONTAINS(LCASE(?type), "king of jerusalem"))
  
  OPTIONAL {
    ?activity crm:P4_has_time-span ?timespan .
    ?timespan crm:P82a_begin_of_the_begin ?start ;
              crm:P82b_end_of_the_end ?end .
  }
}
ORDER BY ?start
```

### Query 2: Family Network of Baldwin II

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX sdhss: <https://sdhss.org/ontology/core/>

SELECT ?relType ?relatedPerson ?relatedName
WHERE {
  wd:Q30578 sdhss:P1_is_child_of ?relatedPerson .  # Baldwin II's parents
  
  ?relatedPerson crm:P1_is_identified_by/crm:P190_has_symbolic_content ?relatedName .
  
  BIND("parent" AS ?relType)
  
  UNION
  
  {
    wd:Q30578 sdhss:P2_is_parent_of ?relatedPerson .  # Baldwin II's children
    ?relatedPerson crm:P1_is_identified_by/crm:P190_has_symbolic_content ?relatedName .
    BIND("child" AS ?relType)
  }
}
```

### Query 3: Persons Needing Review

```sparql
PREFIX outremer: <https://thodel.github.io/outremer/data/>
PREFIX sdhss: <https://sdhss.org/ontology/core/>

SELECT ?person ?name ?source
WHERE {
  ?person a crm:E21_Person ;
          crm:P1_is_identified_by/crm:P190_has_symbolic_content ?name ;
          sdhss:P100_needs_review true ;
          sdhss:P101_extraction_source ?source .
}
LIMIT 100
```

---

## Appendix B: SHACL Shape Example

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix sdhss: <https://sdhss.org/ontology/core/> .

sdhss:PersonShape
    a sh:NodeShape ;
    sh:targetClass crm:E21_Person ;
    
    # Every person must have at least one name
    sh:property [
        sh:path crm:P1_is_identified_by/crm:P190_has_symbolic_content ;
        sh:minCount 1 ;
        sh:message "Every person must have at least one name" ;
    ] ;
    
    # If birth date exists, it must be a valid year
    sh:property [
        sh:path crm:P98i_was_born/crm:P4_has_time-span/crm:P82a_begin_of_the_begin ;
        sh:datatype xsd:gYear ;
        sh:message "Birth date must be a valid year (YYYY)" ;
    ] ;
    
    # Social representations should use controlled vocabulary
    sh:property [
        sh:path crm:P129_is_about/sdhss:P1_refers_to ;
        sh:pattern "^[A-Z].*" ;
        sh:message "Social representation labels should start with capital letter" ;
    ] .
```

---

## Appendix C: Next Steps

### Immediate (This Week)

1. **Decide on triplestore**: GraphDB vs. Jena vs. Blazegraph
2. **Install on VM**: Run installation script
3. **Test SDHSS download**: Verify Ontome accessibility
4. **Create sample mapping**: Convert 10 persons manually

### Short-term (Next Month)

1. **Full data migration**: Transform all 19,085 persons
2. **Set up SPARQL endpoint**: Make it publicly accessible
3. **Design reconciliation UI**: Mockups and wireframes
4. **Write grant proposal**: SNSF Digital Humanities (deadline March/April)

### Medium-term (3-6 Months)

1. **Launch beta**: Invite 5-10 DH colleagues to test
2. **Iterate based on feedback**: Improve UX, fix bugs
3. **Publish paper**: Document methodology and results
4. **Present at conference**: DH2026 or similar

---

**Ready to proceed?** Start with installing GraphDB on the VM and testing the SDHSS ontology download. The full implementation can be done incrementally over 6-8 weeks.

🏰✨
