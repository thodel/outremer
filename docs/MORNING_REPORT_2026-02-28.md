# Morning Report — 2026-02-28 07:30 CET

**Generated:** 2026-02-27 21:40 UTC (pre-scheduled)  
**Delivery:** Discord DM to Tobias (channel: 1474120175350583326)  
**Cron:** `30 6 * * *` (7:30 CET daily)

---

## 📊 Knowledge Graph Status

### Fuseki Triplestore
- **Status:** ⚠️ Running but endpoints not accessible
- **Issue:** Webapp context initialization failure (Jetty temp directory)
- **Triples:** Not yet loaded (pending endpoint fix)
- **Dataset:** `/var/lib/fuseki/databases/outremer/` (empty)

### RDF Export
- **File:** `data/unified_kg.ttl`
- **Size:** 8.67 MB
- **Status:** ✅ Ready to load
- **Entities:** 19,085 persons

### Outremer Project
- **H-i-t-L Decisions:** 11 total (8 reject, 3 accept) — check for new
- **Upload Queue:** 0 pending — check for new uploads
- **Website:** https://thodel.github.io/outremer/ (live)
- **KG Search:** ✅ Implemented on people.html (expandable panel)

---

## 🎯 Priority Tasks for Today

1. **Fix Fuseki endpoint issue** (estimated 1-2 hours)
   - Debug Jetty webapp configuration
   - Or try Blazegraph as alternative
   - Goal: Get SPARQL endpoint working at http://localhost:3030/outremer/query

2. **Load RDF data** (estimated 30 minutes)
   - Command: `curl -X POST 'http://localhost:3030/outremer/data' -H 'Content-Type: text/turtle' --data-binary @data/unified_kg.ttl`
   - Verify: `curl 'http://localhost:3030/outremer/query?query=SELECT%20(COUNT(*)%20as%20?c)%20WHERE%20%7B%20?s%20?p%20?o%20%7D'`

3. **Test SPARQL queries** (estimated 1 hour)
   - Run sample queries from `docs/KG_INGESTION_PROPOSAL.md`
   - Verify results match expected data

4. **Check Outremer queues**
   - New H-i-t-L decisions? → Notify scholars
   - New uploads? → Process or reject

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `docs/KG_INGESTION_PROPOSAL.md` | Full technical proposal (19 KB) |
| `docs/KG_DEPLOYMENT_STATUS.md` | Detailed status report |
| `scripts/kg/export_to_rdf.py` | RDF export script |
| `scripts/kg/install_fuseki.sh` | Fuseki installation |
| `data/unified_kg.ttl` | RDF data (ready to load) |
| `/home/th/scripts/kg-morning-report.sh` | This report generator |

---

## 🔧 Quick Commands

```bash
# Check Fuseki status
systemctl status fuseki

# Restart Fuseki
sudo systemctl restart fuseki

# Test endpoint (once working)
curl 'http://localhost:3030/outremer/query?query=ASK%20%7B%7D'

# Load RDF data (once endpoint works)
cd /home/th/repos/outremer
curl -X POST 'http://localhost:3030/outremer/data' \
     -H 'Content-Type: text/turtle' \
     --data-binary @data/unified_kg.ttl

# Count triples (once loaded)
curl 'http://localhost:3030/outremer/query' \
     -H 'Content-Type: application/x-www-form-urlencoded' \
     -d 'query=SELECT (COUNT(*) as ?c) WHERE { ?s ?p ?o }'
```

---

## 📞 Contact

**Prepared by:** cl-bot  
**For:** Tobias Hodel  
**Project:** People of the Levante (Outremer)

---

*This report will be auto-generated daily at 07:30 CET and sent via Discord.*
