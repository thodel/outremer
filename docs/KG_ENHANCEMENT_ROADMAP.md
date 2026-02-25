# Outremer KG Enhancement - Implementation Roadmap

**Priority:** Start with highest-impact, lowest-effort sources first

---

## 🚀 Quick Start (Week 1)

### Task 1.1: FMG MedLands Scraper
**Goal:** Extract crusader nobility from Foundation for Medieval Genealogy

**Files to create:**
```bash
scripts/scrape_fmg_medlands.py
```

**Target sections:**
- `KingsOfJerusalem.htm` (~50 persons)
- `TripoliComtes.htm` (~30 persons)
- `AntiochPrinces.htm` (~25 persons)
- `EdessaComtes.htm` (~20 persons)
- `Byzantium.htm` (imperial family, ~100 persons)

**Expected output:** `data/fmg_medlands_crusaders.json`
```json
{
  "source": "FMG MedLands",
  "url": "http://fmg.ac/Projects/MedLands/",
  "persons": [
    {
      "name": "Baldwin I of Jerusalem",
      "floruit": "1100-1118",
      "title": "King of Jerusalem",
      "family": "House of Boulogne",
      "relations": [
        {"type": "brother", "name": "Godfrey of Bouillon"},
        {"type": "spouse", "name": "Morphia of Melitene"}
      ],
      "sources": ["RHC Hist. Occ.", "William of Tyre"]
    }
  ]
}
```

**Integration:**
```bash
python scripts/build_unified_kg.py --add-source data/fmg_medlands_crusaders.json
```

**Estimated effort:** 4-6 hours  
**Expected yield:** 200-250 crusader nobility

---

### Task 1.2: Wikidata Crusader Query
**Goal:** Auto-fetch all Wikidata entries tagged as "crusader"

**Files to modify:**
```bash
scripts/wikidata_reconcile.py  # Add new SPARQL query
scripts/crusader_wikidata_query.rq  # New query file
```

**SPARQL Query:**
```sparql
SELECT ?person ?personLabel ?birth ?death ?occupation WHERE {
  ?person wdt:P106 wd:Q133492;  # occupation: crusader
          wdt:P570 ?death.
  OPTIONAL { ?person wdt:P569 ?birth }
  OPTIONAL { ?person wdt:P39 ?position }
  FILTER(YEAR(?death) >= 1095 && YEAR(?death) <= 1291)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr,de". }
}
ORDER BY ?death
```

**Integration:**
```bash
python scripts/wikidata_reconcile.py --query scripts/crusader_wikidata_query.rq
```

**Expected yield:** 400-600 crusader QIDs  
**Estimated effort:** 2-3 hours

---

### Task 1.3: Wikipedia Crusader Biographies
**Goal:** Extract structured data from Wikipedia crusader articles

**Files to create:**
```bash
scripts/extract_wikipedia_crusaders.py
```

**Dependencies:**
```bash
pip install pywikibot
```

**Categories to scrape:**
- `Category:Crusaders`
- `Category:Knights of the First Crusade`
- `Category:Knights of the Second Crusade`
- `Category:Kings of Jerusalem`
- `Category:Princes of Antioch`
- `Category:Counts of Tripoli`

**Expected output:** `data/wikipedia_crusaders.json`

**Estimated effort:** 3-4 hours  
**Expected yield:** 300-400 persons (many overlap with Wikidata)

---

## 📅 Week 2-3: Medium-Term Enhancements

### Task 2.1: PGMA Data Request
**Goal:** Establish contact and request data sharing

**Action items:**
1. Email PGMA maintainers (contact@pgma.de)
2. Propose collaboration/integration
3. Request bulk export or API access
4. Discuss licensing (CC-BY-SA preferred)

**Template email:**
```
Dear PGMA Team,

I am writing on behalf of the Outremer project, a digital humanities initiative 
to build a comprehensive knowledge graph of persons involved in the medieval 
Levant during the crusading period (1095-1291).

Your Prosopographica Genealogica Medii Aevi database is an invaluable resource 
that would significantly enhance our coverage of crusader families and their 
connections to broader European nobility...

[Continue with specific request]
```

**Estimated effort:** 1-2 hours (plus waiting time)

---

### Task 2.2: Charter NER Pilot
**Goal:** Test NER on one cartulary volume

**Source:** Delaville Le Roulx, _Cartulaire général de l'Ordre des Hospitaliers_, Vol. 1 (1100-1200)

**Available at:**
- Gallica: https://gallica.bnf.fr/ark:/12148/bpt6k50448j
- Internet Archive: Multiple scans

**Files to modify:**
```bash
scripts/extract_persons_google.py  # Add Latin/Old French support
scripts/process_cartulary.py  # New script for charter processing
```

**Pipeline:**
1. OCR scan (if needed) → `data/raw/hospitaliers_vol1.txt`
2. Run NER with Latin language hint
3. Extract witness lists specifically
4. Link to existing authority file

**Estimated effort:** 8-10 hours  
**Expected yield:** 100-150 witnesses (many minor nobles)

---

### Task 2.3: Military Orders Prosopography
**Goal:** Compile published member lists

**Sources:**
- Jotischky, _The Crusades and the Military Orders_ (2001)
- Riley-Smith, _The Knights of St John in Jerusalem and Cyprus_ (1967)
- Barber, _The New Knighthood: A History of the Order of the Temple_ (1994)

**Files to create:**
```bash
data/manual/military_orders_members.csv
```

**CSV format:**
```csv
name,order,rank,start_date,end_date,posted_at,source
"Hugh de Payens","templar","Grand Master","1119","1136","Jerusalem","Barber 1994"
"Raymond du Puy","hospitaller","Grand Master","1120","1158","Rhodes","Riley-Smith 1967"
```

**Integration:**
```bash
python scripts/build_unified_kg.py --add-csv data/manual/military_orders_members.csv
```

**Estimated effort:** 6-8 hours (manual data entry)  
**Expected yield:** 150-200 order members

---

## 🗓️ Month 2-3: Advanced Integrations

### Task 3.1: Arabic Sources Partnership
**Goal:** Begin collaboration with Islamic Studies

**Potential partners:**
- Prof. Dr. [Name], Institute of Islamic Studies, University of Bern
- Dr. [Name], Center for Medieval Studies, nearby institutions

**Proposal outline:**
1. Joint prosopography of Muslim elites (1095-1291)
2. Bilingual authority entries (Arabic/English)
3. Apply Arabic NER tools (CamelTools, Farasa)
4. Target biographical dictionaries:
   - Ibn Khallikān, _Wafayāt al-Aʿyān_
   - al-Dhahabī, _Siyar Aʿlām al-Nubalāʾ_
   - Ibn al-Athīr, _al-Kāmil fī al-Taʾrīkh_

**Funding targets:**
- SNSF Digital Humanities Grant (deadline: March/April)
- EU Horizon Europe Cluster 2 (rolling deadlines)

**Estimated effort:** 10-15 hours (proposal writing + meetings)

---

### Task 3.2: Network Analysis Layer
**Goal:** Add graph database for relationship queries

**Technology choice:** Neo4j (community edition, free)

**Installation:**
```bash
# On VM
wget https://neo4j.com/artifact.php?name=neo4j-community-5.x.x-unix.tar.gz
tar xzf artifact.php
cd neo4j-community-5.x.x
./bin/neo4j start
```

**Data model:**
```cypher
CREATE (p:Person {id: "AUTH:CR1", name: "Conrad III"})
CREATE (g:Person {id: "AUTH:CR2", name: "Godfrey"})
CREATE (p)-[:BROTHER_OF]->(g)
CREATE (p)-[:PARTICIPATED_IN {year: 1147}]->(c:Crusade {name: "Second Crusade"})
```

**Queries to enable:**
- "Show all vassals of Baldwin III"
- "Find all Templars posted at Krak des Chevaliers"
- "Trace family connections between crusader leaders"
- "Visualize network of charter witnesses"

**Files to create:**
```bash
scripts/export_to_neo4j.py
queries/network_queries.cypher
```

**Estimated effort:** 12-16 hours  
**Timeline:** End of Month 2

---

## 📊 Success Metrics

| Metric | Current | After Phase 1 | After Phase 2 | After Phase 3 |
|--------|---------|---------------|---------------|---------------|
| Total persons | 19,085 | 19,600 (+3%) | 20,200 (+6%) | 21,500 (+13%) |
| Crusader-specific | ~500 | ~1,200 | ~1,800 | ~2,500 |
| Authority linking | 16% | 25% | 35% | 45% |
| Islamic figures | ~20 | ~50 | ~150 | ~400 |
| Family relations | sparse | moderate | rich | comprehensive |
| Charter witnesses | 0 | ~100 | ~250 | ~500 |

---

## 🎯 Recommended Starting Point

**Start TODAY with Task 1.1 (FMG MedLands scraper)**

**Why?**
- ✅ Highest signal-to-noise ratio
- ✅ Well-structured HTML (easy to parse)
- ✅ Immediate impact on crusader nobility coverage
- ✅ No permissions/API keys needed
- ✅ Can complete in one afternoon

**Command to get started:**
```bash
cd /home/th/repos/outremer
mkdir -p scripts scrapers data/fmg
nano scripts/scrape_fmg_medlands.py
```

**Sample scraper skeleton:**
```python
#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import json

BASE_URL = "http://fmg.ac/Projects/MedLands/"
PAGES = [
    "KINGSofJERUSALEM.htm",
    "TRIPOLI.htm",
    "ANTIOCH.htm",
    "EDESSA.htm",
]

def parse_medlands_page(url):
    resp = requests.get(url)
    soup = BeautifulSoup(resp.text, 'html.parser')
    persons = []
    
    # Parse structure (adjust selectors based on actual HTML)
    for section in soup.find_all('p', class_='Normal'):
        if contains_person_name(section):
            person = extract_person_data(section)
            persons.append(person)
    
    return persons

if __name__ == "__main__":
    all_persons = []
    for page in PAGES:
        url = BASE_URL + page
        print(f"Scraping {url}...")
        persons = parse_medlands_page(url)
        all_persons.extend(persons)
    
    output = {
        "source": "FMG MedLands",
        "url": BASE_URL,
        "persons": all_persons
    }
    
    with open("data/fmg_medlands_crusaders.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Extracted {len(all_persons)} persons")
```

---

## 📝 Weekly Checkpoints

### Week 1 Review (2026-03-03)
- [ ] FMG MedLands scraper completed
- [ ] Wikidata crusader query integrated
- [ ] Wikipedia extraction running
- [ ] **Target:** +500 crusader persons in KG

### Week 2-3 Review (2026-03-17)
- [ ] PGMA contact established
- [ ] Charter NER pilot completed
- [ ] Military orders CSV compiled
- [ ] **Target:** +800 additional persons

### Month 2 Review (2026-04-01)
- [ ] Arabic sources partnership initiated
- [ ] Neo4j graph database deployed
- [ ] First funding proposal submitted
- [ ] **Target:** +1,500 total new persons

---

**Ready to begin?** Start with the FMG MedLands scraper this afternoon! 🚀
