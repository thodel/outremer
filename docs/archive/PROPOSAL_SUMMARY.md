# Outremer Reconciliation & SDHSS Migration - Executive Summary

**Created:** 2026-02-25  
**Status:** Ready for implementation

---

## 🎯 What Was Requested

1. **New webpage section** for dataset reconciliation (under "Contribute Your Knowledge")
2. **SDHSS ontology adoption** (from https://ontome.net/namespace/11)
3. **Open-source setup** that runs on current VM (194.13.80.183)

---

## ✅ What Was Delivered

### Three Documentation Files

| File | Purpose | Size |
|------|---------|------|
| `RECONCILIATION_INTERFACE_PROPOSAL.md` | Full technical proposal | 21 KB |
| `SDHSS_QUICKSTART.md` | 30-minute setup guide | 8 KB |
| `PROPOSAL_SUMMARY.md` | This executive summary | 3 KB |

---

## 📋 Key Proposals

### 1. Reconciliation Interface

**Purpose:** Let scholars review and merge person records from multiple sources

**Features:**
- Dashboard with statistics
- Review queue (610 persons flagged as "needs review")
- Side-by-side comparison view
- Merge/split tools
- User authentication & attribution
- Gamification (badges, ORCID integration)

**Tech Stack:**
- Frontend: React 18 + Material-UI
- Backend: FastAPI (Python)
- Database: PostgreSQL + pg_trgm
- Matching algorithm: Fuzzy name matching + relation overlap

**Estimated effort:** 4-6 weeks development

---

### 2. SDHSS Ontology Migration

**What is SDHSS?**
- Extension of CIDOC CRM for humanities/social sciences
- Models historical epistemic distance
- Supports social representations & collective intentionality
- Used by LOD4HSS projects

**Benefits:**
- Semantic interoperability (FAIR principles)
- Rich property graph (100+ properties vs. current flat structure)
- Native temporal reasoning
- SPARQL query support
- RDF/OWL standard format

**Migration Path:**
```
Current JSON → RDF/Turtle → GraphDB → SPARQL endpoint
```

**Estimated effort:** 2-3 weeks (including testing)

---

### 3. Infrastructure Recommendation

**Recommended:** GraphDB Free Edition

**Why?**
- ✅ Runs on current VM (Ubuntu 24.04, 4-8 GB RAM)
- ✅ Free for academic use (up to 50M triples)
- ✅ Excellent web UI (no SPARQL knowledge needed for browsing)
- ✅ Built-in SHACL validation
- ✅ Easy maintenance (single binary)

**Resource Requirements:**
- RAM: 2-4 GB
- Storage: ~10 GB (current KG = ~1M triples)
- CPU: Minimal (mostly idle, queries are fast)

**Alternative:** Apache Jena Fuseki (fully open source, but less user-friendly)

---

## 🗓️ Implementation Timeline

### Phase 1: Foundation (Weeks 1-2)
- Install GraphDB on VM
- Configure Caddy reverse proxy
- Download SDHSS ontology
- Test with 100-person sample

### Phase 2: Migration (Weeks 2-3)
- Convert full KG (19,085 persons → RDF)
- Validate with SHACL
- Load into GraphDB
- Write example SPARQL queries

### Phase 3: Reconciliation UI (Weeks 3-6)
- Build frontend (React/Vue)
- Create backend API
- Implement matching algorithm
- Add user authentication
- Beta testing

### Phase 4: Launch (Weeks 6-8)
- Deploy to production
- Documentation
- Community outreach
- Iterate based on feedback

---

## 💰 Cost Estimate

| Item | Cost |
|------|------|
| Infrastructure | CHF 0 (existing VM) |
| GraphDB Free | CHF 0 (academic license) |
| Domain/DNS | CHF 0 (hodelweb.ch owned) |
| Development | CHF 0-500 (optional student assistant) |
| **Total** | **CHF 0-500** |

**Ongoing costs:** None

---

## 📊 Current Data Status

| Source | Persons | Status |
|--------|---------|--------|
| Outremer Authority | 126 | ✅ Curated |
| Wikidata Peerage | 18,349 | ✅ Integrated |
| FMG MedLands | 628 | ✅ Just added (needs review) |
| Riley-Smith | ~400 | ✅ Extracted |
| Munro-Popes | ~200 | ✅ Extracted |
| **Total in KG** | **19,085** | **✅ Unified** |
| Needs Review | 610 | ⚠️ Reconciliation needed |

---

## 🚀 Quick Start (30 Minutes)

If you want to test SDHSS migration **today**:

```bash
# 1. SSH to VM
ssh th@194.13.80.183

# 2. Follow SDHSS_QUICKSTART.md
#    - Install GraphDB (5 min)
#    - Download ontologies (3 min)
#    - Create repository (5 min)
#    - Convert KG to RDF (10 min)
#    - Load data (5 min)
#    - Test SPARQL (2 min)
```

Full instructions: `docs/SDHSS_QUICKSTART.md`

---

## 🔍 Example Use Cases

### For Scholars

**Query:** "Show me all Kings of Jerusalem with their family relations"

```sparql
SELECT ?king ?name ?parent ?child
WHERE {
  ?king a crm:E21_Person ;
        crm:P14_carried_out [crm:P2_has_type "King of Jerusalem"] ;
        crm:P1_is_identified_by/crm:P190_has_symbolic_content ?name .
  
  OPTIONAL { ?king sdhss:P1_is_child_of ?parent }
  OPTIONAL { ?king sdhss:P2_is_parent_of ?child }
}
```

### For Community Contributors

**Task:** Review potential duplicate entries

1. Log in to reconcile.outremer.org
2. Open "Review Queue"
3. See side-by-side comparison
4. Click "Merge" or "Mark as different"
5. Earn badges for contributions

### For DH Researchers

**Access:** SPARQL endpoint at sparql.hodelweb.ch

- Query across all datasets simultaneously
- Export results as CSV, JSON-LD, or RDF
- Link to other LOD4HSS projects
- Cite specific dataset versions

---

## 📚 Technical Details

See full proposal for:
- Complete UI wireframes
- Data model specifications
- Matching algorithm pseudo-code
- SHACL shape examples
- 10+ example SPARQL queries
- Complete installation scripts

File: `docs/RECONCILIATION_INTERFACE_PROPOSAL.md`

---

## 🎓 Academic Output Potential

This infrastructure enables:

1. **Conference paper:** "Community-Driven Reconciliation of Historical Prosopography Data"
   - Target: DH2026, Digital Humanities Conference
   
2. **Journal article:** "Modeling Medieval Crusader Networks with SDHSS Ontology"
   - Target: Digital Humanities Quarterly, Journal of Digital History

3. **Grant proposal:** SNSF Digital Humanities Grant
   - Deadline: March/April 2026
   - Budget: CHF 150K for doctoral position + development

4. **Workshop:** "Introduction to Semantic Web for Historians"
   - Hands-on training with Outremer platform

---

## ⚡ Decision Points

### Need Your Input On:

1. **Triplestore choice:**
   - GraphDB Free (recommended, proprietary but free)
   - Apache Jena Fuseki (fully open source)
   - Blazegraph (high performance, complex)

2. **Development priority:**
   - SDHSS migration first? (2-3 weeks)
   - Reconciliation UI first? (4-6 weeks)
   - Both in parallel?

3. **User authentication:**
   - Simple email/password?
   - OAuth (Google, GitHub)?
   - ORCID (academic standard)?

4. **Hosting:**
   - Keep on current VM? (yes, sufficient)
   - Separate subdomain? (sparql.hodelweb.ch, reconcile.hodelweb.ch)

---

## 👉 Next Steps

### Option A: Start Immediately (Recommended)

```bash
# This afternoon:
ssh th@194.13.80.183
# Follow SDHSS_QUICKSTART.md
# Have working SDHSS triplestore in 30 minutes
```

### Option B: Review First

1. Read full proposal (20 min)
2. Test GraphDB demo online (10 min)
3. Decide on priorities
4. Start implementation

### Option C: Discussion

Schedule 30-min call to discuss:
- Technical questions
- Priority setting
- Resource allocation
- Grant opportunities

---

## 📞 Questions?

All documentation is in: `/home/th/repos/outremer/docs/`

- **Full proposal:** RECONCILIATION_INTERFACE_PROPOSAL.md
- **Quick start:** SDHSS_QUICKSTART.md
- **FMG scraper docs:** scrapers/README_FMG_SCRAPER.md

Ready to proceed? Just say the word and I can:
1. Install GraphDB on the VM right now
2. Start the SDHSS conversion
3. Begin designing the reconciliation UI

🏰✨
