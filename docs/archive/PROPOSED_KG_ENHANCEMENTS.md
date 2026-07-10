# Proposed Enhancements for Outremer Knowledge Graph

**Date:** 2026-02-24  
**Status:** Research & Recommendations

---

## Executive Summary

The Outremer project has successfully integrated:
- ✅ 126 curated authority persons (Omeka XML)
- ✅ ~18,349 Wikidata Peerage pre-1500 persons
- ✅ NER extraction pipeline with contextual matching
- ✅ Human-in-the-loop reconciliation interface

**Next frontier:** Integrate specialized crusader prosopography databases to dramatically improve coverage, accuracy, and scholarly value.

---

## 1. Priority Research Databases for Integration

### 🥇 **Tier 1: Essential Crusader-Specific Resources**

#### 1.1 **Prosopographica Genealogica Medii Aevi (PGMA)**
- **URL:** https://www.pgma.de/
- **Coverage:** 10,000+ medieval persons (9th-15th centuries)
- **Relevance:** ⭐⭐⭐⭐⭐ Critical for Outremer
- **Data available:** Names, family relations, offices, dates, sources
- **Format:** Online database, some RDF/TEI exports
- **Integration approach:**
  - Scrape/search via API if available
  - Manual export for key crusader families
  - Match via normalized names + floruit dates
- **Estimated new persons:** 500-800 crusaders/nobles

#### 1.2 **Foundation for Medieval Genealogy (FMG)**
- **URL:** http://fmg.ac/Projects/MedLands/
- **Coverage:** Comprehensive medieval nobility genealogies
- **Relevance:** ⭐⭐⭐⭐⭐ Essential for crusader nobility
- **Data available:** Family trees, succession, marriages, primary sources
- **Format:** HTML pages (structured), some GEDCOM
- **Integration approach:**
  - Parse MedLands sections on:
    - Kings of Jerusalem
    - Counts of Tripoli, Edessa, Antioch
    - Byzantine imperial family (related to crusades)
    - Muslim dynasties (Seljuks, Ayyubids, Mamluks)
  - Extract structured data from narrative genealogies
- **Estimated new persons:** 300-500 crusader nobility

#### 1.3 **The Crusades Wiki (Wikimedia/Fandom)**
- **URL:** https://crusades.fandom.com/ or https://en.wikipedia.org/wiki/Category:Crusades
- **Coverage:** Crowdsourced but well-sourced crusader biographies
- **Relevance:** ⭐⭐⭐⭐ High (aggregates academic sources)
- **Data available:** Biographies, battles, castles, orders
- **Format:** MediaWiki (scrapable)
- **Integration approach:**
  - Use Wikimedia API for Wikipedia crusader articles
  - Extract infobox data (dates, titles, battles)
  - Cross-reference with existing Wikidata QIDs
- **Estimated new persons:** 200-400 (many already in Wikidata)

---

### 🥈 **Tier 2: Specialized Scholarly Databases**

#### 2.1 **Chartes de Terre Sainte (Cartularies of the Holy Land)**
- **URL:** Various editions (e.g., Delaville Le Roulx cartulary)
- **Coverage:** Charters from Kingdom of Jerusalem (12th-13th centuries)
- **Relevance:** ⭐⭐⭐⭐⭐ Primary source goldmine
- **Data available:** Witness lists, property transfers, legal documents
- **Format:** Printed editions, some digitized (Gallica, Internet Archive)
- **Integration approach:**
  - OCR + NER on digitized cartularies
  - Extract witness names, titles, relationships
  - Link to authority file via prosopographical analysis
- **Estimated new persons:** 400-600 (many minor nobles, burgesses)

#### 2.2 **Rolls Series / Recueil des Historiens des Croisades (RHC)**
- **URL:** https://gallica.bnf.fr/ (search "Recueil des historiens des croisades")
- **Coverage:** Chroniclers' accounts, royal charters
- **Relevance:** ⭐⭐⭐⭐⭐ Core primary sources
- **Data available:** Narrative mentions, titles, events
- **Format:** PDF/DjVu (Gallica), some TEI transcriptions
- **Integration approach:**
  - Use existing NER pipeline on RHC texts
  - Extract person mentions with context
  - Add to KG as "mentioned in chronicle" relationships
- **Estimated new persons:** 300-500

#### 2.3 **Military Orders Prosopography**
- **Resources:**
  - **Knights Templar:** Malcolm Barber's database, Vatican archives
  - **Knights Hospitaller:** RHodE (Rhodes Hospitaller Database)
  - **Teutonic Knights:** Deutschordenszentralarchiv (Vienna)
- **Coverage:** Members of military orders (12th-16th centuries)
- **Relevance:** ⭐⭐⭐⭐ Critical for Outremer society
- **Data available:** Names, ranks, postings, transactions
- **Format:** Archival records, published prosopographies
- **Integration approach:**
  - Start with published prosopographies (e.g., Jotischky, Riley-Smith)
  - Extract member lists with dates/locations
  - Link to existing authority entries
- **Estimated new persons:** 200-400 order members

---

### 🥉 **Tier 3: Complementary Resources**

#### 3.1 **Six Degrees of Francis Bacon (SDFB)**
- **URL:** http://www.sixdegreesoffrancisbacon.com/
- **Coverage:** Early modern British persons (extends to late medieval)
- **Relevance:** ⭐⭐⭐ Some overlap with later crusader historiography
- **Data available:** Social networks, correspondence
- **Format:** RDF, API available
- **Integration approach:** Query API for persons with "crusade" or "Outremer" tags

#### 3.2 **Medieval Prosopography Portal (MPD)**
- **URL:** Various national projects (German, French, British)
- **Coverage:** Regional medieval prosopographies
- **Relevance:** ⭐⭐⭐ Variable (depends on region)
- **Integration approach:** Identify crusader-related entries via keyword search

#### 3.3 **Islamic Prosopography Databases**
- **Resources:**
  - **Taʾrīkh al-Islām** (various editions)
  - **Siyar Aʿlām al-Nubalāʾ** (al-Dhahabī)
  - **Wafayāt al-Aʿyān** (Ibn Khallikān)
- **Coverage:** Muslim elites, emirs, scholars (contemporary with crusades)
- **Relevance:** ⭐⭐⭐⭐⭐ Essential for balanced perspective
- **Data available:** Biographies, death dates, offices
- **Format:** Arabic texts, some English translations
- **Integration approach:**
  - Partner with Islamic studies scholars
  - Use Arabic NER tools (CamelTools, Farasa)
  - Create parallel Arabic/English authority entries
- **Estimated new persons:** 400-700 Muslim figures

---

## 2. Technical Integration Strategy

### Phase 1: Quick Wins (1-2 weeks)

1. **Wikidata Enhancement**
   ```bash
   # Query Wikidata for crusader-specific properties
   SELECT ?person ?personLabel WHERE {
     ?person wdt:P106 wd:Q133492;  # occupation: crusader
             wdt:P570 ?death.
     FILTER(YEAR(?death) < 1300)
   }
   ```
   - Add ~500 crusader-specific QIDs to watchlist
   - Auto-link extracted persons matching these QIDs

2. **Wikipedia/MediaWiki Scraping**
   - Use Pywikibot to extract crusader biographies
   - Parse infoboxes for structured data
   - Merge with existing Wikidata matches

3. **FMG MedLands Parsing**
   - Write scraper for key sections:
     - `KingsOfJerusalem.htm`
     - `TripoliComtes.htm`
     - `AntiochPrinces.htm`
   - Extract names, dates, family relations
   - Add as separate source in unified KG

### Phase 2: Medium-Term (1-2 months)

4. **PGMA Integration**
   - Contact PGMA maintainers for data sharing agreement
   - Request bulk export or API access
   - Develop matching algorithm for name variants

5. **Charter NER Pipeline**
   - Extend `extract_persons_google.py` for Latin/Old French
   - Process digitized cartularies (Delaville Le Roulx, etc.)
   - Add charter witnesses to KG with provenance

6. **Military Orders Database**
   - Compile published prosopographies into CSV
   - Import via `build_unified_kg.py`
   - Tag with `source: military_order_prosopography`

### Phase 3: Long-Term (3-6 months)

7. **Arabic Sources Integration**
   - Partner with University of Bern Islamic Studies
   - Apply Arabic NER to biographical dictionaries
   - Create bilingual authority entries (Arabic/English)

8. **Network Analysis Layer**
   - Add graph database (Neo4j) for relationship queries
   - Visualize family networks, vassalage chains
   - Identify "missing links" in prosopography

---

## 3. Data Model Extensions

### New Properties to Track

```typescript
interface EnhancedPerson extends UnifiedPerson {
  // === Crusade-Specific Metadata ===
  crusades?: Array<{
    number: string;           // "First", "Second", "Children's"
    year_joined: string;
    role: string;             // "leader", "participant", "chronicler"
    battles?: string[];       // ["Dorylaeum", "Ascalon"]
  }>;
  
  // === Feudal Relationships ===
  feudal_relations?: Array<{
    type: "liege" | "vassal" | "homage";
    person_id: string;
    fief?: string;            // "County of Jaffa"
    start_date?: string;
    end_date?: string;
  }>;
  
  // === Military Order Membership ===
  order_membership?: {
    order: "templar" | "hospitaller" | "teutonic" | "lazarus";
    rank: string;             // "Knight Brother", "Grand Master"
    joined_date?: string;
    posted_at?: string;       // "Krak des Chevaliers"
  };
  
  // === Charter Appearances ===
  charter_witnesses?: Array<{
    charter_id: string;
    date: string;
    location: string;
    role: "witness" | "grantor" | "beneficiary";
  }>;
  
  // === Source Citations ===
  sources: Array<{
    type: "chronicle" | "charter" | "genealogy" | "prosopography";
    citation: string;         // "RHC Hist. Occ. II, p. 453"
    url?: string;
    confidence: number;
  }>;
}
```

### Updated Matching Strategy

Add **crusade-specific matching signals**:

```python
def calculate_match_score(extracted, candidate):
    score = base_fuzzy_match(extracted.name, candidate.preferred_label)
    
    # Boost if both participated in same crusade
    if extracted.crushade_number and candidate.crushade_number:
        if extracted.crushade_number == candidate.crushade_number:
            score += 0.15
    
    # Boost if feudal relationship matches
    if extracted.liege_lord and candidate.feudal_relations:
        for rel in candidate.feudal_relations:
            if rel.type == "liege" and normalize(rel.person_label) == normalize(extracted.liege_lord):
                score += 0.20
    
    # Boost if same military order
    if extracted.order and candidate.order_membership:
        if extracted.order == candidate.order_membership.order:
            score += 0.25
    
    # Penalize anachronisms
    if extracted.date_mention and candidate.bio.death:
        if years_between(extracted.date_mention, candidate.bio.death) > 50:
            score -= 0.50
    
    return min(score, 1.0)
```

---

## 4. Expected Impact

### Coverage Improvements

| Source | Estimated New Persons | Overlap with Existing | Net Gain |
|--------|----------------------|----------------------|----------|
| PGMA | 600 | 40% | 360 |
| FMG MedLands | 400 | 60% | 160 |
| Charters (NER) | 500 | 20% | 400 |
| Military Orders | 300 | 50% | 150 |
| Islamic Sources | 500 | 10% | 450 |
| **Total** | **2,300** | **~35%** | **~1,520** |

**Current KG:** 19,085 persons  
**After enhancement:** ~20,600 persons (+8% growth, but much higher quality for crusader-specific entries)

### Quality Improvements

- **Authority linking:** Increase from 16% to ~40% for crusader-era persons
- **Contextual matching:** Reduce false positives by 30-40%
- **Network completeness:** Fill gaps in feudal/family relationships
- **Scholarly credibility:** Cite primary sources (charters, chronicles)

---

## 5. Recommended Next Steps

### Immediate (This Week)

1. **Prioritize FMG MedLands scraping**
   - Highest signal-to-noise ratio
   - Well-structured HTML
   - Focus on crusader states nobility

2. **Enhance Wikidata queries**
   - Add crusade-specific SPARQL queries to `wikidata_reconcile.py`
   - Auto-fetch QIDs for known crusaders

3. **Document integration plan**
   - Create GitHub issue tracking each database
   - Assign priority levels
   - Estimate effort for each

### Short-Term (Next Month)

4. **Contact PGMA maintainers**
   - Inquire about data sharing
   - Explore collaboration opportunities

5. **Pilot charter NER**
   - Select one cartulary (e.g., Delaville Le Roulx Vol. 1)
   - Test Latin/French extraction
   - Evaluate quality

### Medium-Term (Next Quarter)

6. **Begin Arabic sources partnership**
   - Reach out to Islamic Studies colleagues at UniBern
   - Propose joint prosopography project
   - Apply for DH funding (SNF, NEH)

---

## 6. Potential Collaborations

### Academic Partners

- **University of Bern Digital Humanities** (existing connection)
  - Prof. Tobias Hodel (you!) - project lead
  - Medieval History Department - domain expertise
  - Islamic Studies - Arabic sources

- **Prosopographica et Genealogica Project** (Cambridge)
  - Leaders in medieval prosopography methods
  - Potential methodology exchange

- **Virtuelles Deutsches Urkundenarchiv**
  - Digital charter infrastructure
  - Technical collaboration on NER

### Funding Opportunities

- **Swiss National Science Foundation (SNSF)**
  - Digital Humanities grants
  - International cooperation supplements

- **NEH Digital Humanities Advancement Grants**
  - For US-based collaborators
  - Infrastructure development

- **EU Horizon Europe**
  - Cluster 2: Culture, Creativity, Inclusive Society
  - Larger-scale integration projects

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Database access denied | Medium | High | Start with open-access sources; build relationships gradually |
| Data quality inconsistent | High | Medium | Implement strict validation; manual review for low-confidence matches |
| Name variant explosion | High | Medium | Invest in better normalization algorithms; use phonetic matching |
| Scope creep | High | High | Stick to Tier 1 sources first; defer nice-to-haves |
| Maintenance burden | Medium | Medium | Automate updates; document integration patterns |

---

## 8. Conclusion

Integrating specialized crusader prosopography databases will transform Outremer from a general medieval person authority file into **the definitive digital resource for crusader studies**. The combination of:

- ✅ Existing strong foundation (126 curated + 18k Wikidata)
- ✅ Proven NER + reconciliation pipeline
- ✅ Rich contextual matching interface
- 🎯 Targeted integration of 5-7 key databases

...positions the project to become an indispensable tool for medieval historians, digital humanists, and genealogists worldwide.

**Recommended starting point:** FMG MedLands scraping (highest ROI, lowest barrier to entry).

---

**Prepared by:** cl-bot 🤖  
**For:** Prof. Dr. Tobias Hodel, University of Bern  
**Date:** 2026-02-24
