# Knowledge Graph Deployment Status

**Date:** 2026-02-27 21:35 UTC  
**Report Time:** 2026-02-28 07:30 CET (scheduled)  
**Status:** 🟡 Partially Complete

---

## Executive Summary

The Knowledge Graph ingestion pipeline has been **successfully developed and tested**, with RDF export working correctly. Apache Jena Fuseki triplestore is installed but requires additional configuration to resolve webapp context issues before data can be loaded.

**Completion: ~75%**

---

## ✅ Completed Tasks

### 1. RDF Export Pipeline
- **Script:** `scripts/kg/export_to_rdf.py`
- **Output:** `data/unified_kg.ttl` (8.67 MB)
- **Entities:** 19,085 persons converted to SDHSS-aligned RDF/Turtle format
- **Status:** ✅ Working perfectly

**Sample triple:**
```turtle
outremer:AUTH_CR1 a sdhss:Person ;
    sdhss:preferredLabel "Conrad III of Germany" ;
    sdhss:variantName "Conrad", "Conrad III" ;
    sdhss:outremerAuthorityId "AUTH:CR1" ;
    sdhss:confidence "1.0"^^xsd:decimal .
```

### 2. Fuseki Installation
- **Package:** Apache Jena Fuseki 4.10.0
- **Location:** `/opt/fuseki/`
- **Service:** systemd unit configured and enabled
- **Port:** 3030
- **Status:** ✅ Installed and running

### 3. Documentation
- **`docs/KG_INGESTION_PROPOSAL.md`** (19 KB) — Comprehensive proposal with:
  - Data sources inventory
  - SDHSS ontology schema
  - Implementation plan (3 phases)
  - Example SPARQL queries
  - Technical stack recommendations
- **`docs/KG_DEPLOYMENT_STATUS.md`** — This status report

### 4. Installation Scripts
- **`scripts/kg/install_fuseki.sh`** — Automated Fuseki installation
- **`scripts/kg/export_to_rdf.py`** — JSON→RDF conversion

---

## ⚠️ Issues Encountered

### Fuseki Webapp Context Failure

**Error:**
```
java.lang.IllegalStateException: Parent for temp dir not configured correctly: writeable=false
```

**Impact:** The Fuseki webapp fails to initialize, preventing HTTP endpoints from being accessible. The server starts but returns 404 for all requests.

**Attempts to Fix:**
1. ✅ Set `/tmp` permissions to 777
2. ✅ Created dedicated temp directory `/tmp/fuseki`
3. ✅ Configured `JAVA_OPTS=-Djava.io.tmpdir=/tmp/fuseki`
4. ✅ Changed ownership of `/opt/fuseki/webapp/` to fuseki user
5. ✅ Used configuration file approach (`outremer.ttl`)

**Current Status:** Server runs, but webapp context still fails silently. Dataset is created at `/var/lib/fuseki/databases/outremer/` but endpoints are not exposed.

**Next Steps to Resolve:**
1. Try running Fuseki with `--no-webapp` flag (if available)
2. Use Jetty XML configuration for fine-grained control
3. Consider alternative: GraphDB Free (requires registration at ontotext.com)
4. Consider alternative: Blazegraph (open source, easier setup)

---

## 📊 Data Summary

### Current Knowledge Graph
| Metric | Value |
|--------|-------|
| **Total entities** | 19,085 |
| **Entity type** | Person (100%) |
| **With Wikidata QID** | 18,359 (96%) |
| **With Outremer AUTH** | 126 |
| **Needs review** | 610 |
| **RDF file size** | 8.67 MB |
| **Estimated triples** | ~200,000 |

### Data Sources Included
1. ✅ Outremer Authority File (126 persons)
2. ✅ Wikidata Peerage pre-1500 (~18,359 persons)
3. ✅ PDF Extractions (Riley-Smith: 163, Munro-Pope: 93)
4. ✅ FMG MedLands (628 persons)
5. ⏳ DHI Crusaders Database (sample only, full scrape blocked)

---

## 📋 Remaining Tasks

### Priority 1: Resolve Fuseki Issues
- [ ] Fix webapp context initialization
- [ ] Verify SPARQL endpoint accessibility
- [ ] Load `data/unified_kg.ttl` into triplestore
- [ ] Test basic SPARQL queries

### Priority 2: Data Loading
- [ ] Upload RDF data to Fuseki
- [ ] Verify triple count matches expected (~200K)
- [ ] Test sample queries (see proposal document)

### Priority 3: Web Integration
- [ ] Update `site/explorer.html` with SPARQL query interface
- [ ] Add graph visualization (D3.js force-directed)
- [ ] Integrate with existing people.html search

### Priority 4: Future Enhancements (per proposal)
- [ ] Event extraction from PDFs
- [ ] Group extraction (military orders, families)
- [ ] Place geocoding (Geonames API)
- [ ] Entity resolution improvements
- [ ] Incremental ingestion pipeline

---

## 🔧 Technical Details

### Fuseki Configuration
```bash
# Service location
/opt/fuseki/fuseki-server --config=/var/lib/fuseki/outremer.ttl

# Dataset location
/var/lib/fuseki/databases/outremer/

# Config file
/var/lib/fuseki/outremer.ttl
```

### RDF Export Command
```bash
cd /home/th/repos/outremer
.venv/bin/python3 scripts/kg/export_to_rdf.py
```

### Expected Load Command (once working)
```bash
curl -X POST 'http://localhost:3030/outremer/data' \
     -H 'Content-Type: text/turtle' \
     --data-binary @data/unified_kg.ttl
```

### Test Query
```sparql
SELECT ?person ?label WHERE {
  ?person a sdhss:Person ;
          sdhss:preferredLabel ?label .
} LIMIT 10
```

---

## 📅 Timeline

| Phase | Status | ETA |
|-------|--------|-----|
| RDF Export | ✅ Complete | Done |
| Fuseki Setup | ⚠️ Partial | 1-2 hours |
| Data Loading | ⏳ Pending | After Fuseki fix |
| Web UI Integration | ⏳ Pending | 2-3 days |
| Full Pipeline | ⏳ Pending | 1-2 weeks |

---

## 🎯 Recommendations

### Immediate (Today)
1. Try alternative Fuseki configuration (Jetty XML)
2. If unsuccessful, consider Blazegraph as alternative
3. Document working configuration for future deployments

### Short-term (This Week)
1. Complete data loading once triplestore is working
2. Test SPARQL queries from proposal
3. Begin web UI integration

### Medium-term (Next 2-4 Weeks)
1. Implement event/group/place extraction
2. Add entity resolution improvements
3. Set up incremental ingestion pipeline

---

## 📞 Contact

**Prepared by:** cl-bot  
**For:** Tobias Hodel  
**Project:** People of the Levante (Outremer)  
**Repository:** https://github.com/thodel/outremer  
**Documentation:** https://thodel.github.io/outremer/

---

*Last updated: 2026-02-27 21:35 UTC*
