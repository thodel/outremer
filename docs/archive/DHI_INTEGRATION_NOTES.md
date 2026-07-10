# DHI Crusaders Database Integration

## Summary

**Target:** A Database of Crusaders to the Holy Land, 1095-1149  
**URL:** https://www.dhi.ac.uk/crusaders/  
**Records:** ~1,100 crusaders  
**Status:** ⚠️ **Scraping blocked by bot protection (HTTP 403)**

## What We Have

1. **Scraper created:** `scrapers/scrape_dhi_crusaders.py`
   - Fully functional parsing logic
   - Maps to Outremer unified KG schema
   - Handles name variants, relationships, expeditions, sources
   - Rate-limited, browser-like headers

2. **Sample output:** `data/dhi/dhi_sample_output.json`
   - Shows data model mapping
   - 2 example records (IDs 1, 2) scraped before 403 started
   - Demonstrates integration potential

3. **Documentation:** `scrapers/README_DHI_SCRAPER.md`
   - Technical details
   - Bot protection evidence
   - Alternative approaches

## The Problem

The DHI website blocks automated access to person detail pages:

```bash
# Homepage: ✅ Works
curl -A "Mozilla/5.0..." "https://www.dhi.ac.uk/crusaders/"

# Person pages: ❌ 403 Forbidden
curl -A "Mozilla/5.0..." "https://www.dhi.ac.uk/crusaders/person/?id=1"
```

This is likely Cloudflare or similar bot protection that:
- Allows homepage/browse pages
- Blocks direct access to `/person/?id=N`
- May allow access with valid session cookies from browser

## Data Value for Outremer

The DHI database would significantly enrich Outremer:

| Field | Current Outremer | DHI Addition |
|-------|-----------------|--------------|
| Names | ✅ Authority labels | ✅ Variants, modern forms |
| Gender | ❌ Missing | ✅ Male/Female |
| Family | ⚠️ Partial | ✅ Explicit relationships |
| Role | ✅ From sources | ✅ Structured (lay/cleric) |
| Geography | ⚠️ Medieval | ✅ Modern regions |
| Participation | ✅ From sources | ✅ Probability assessed |
| Finance | ❌ Missing | ✅ Mortgages, loans |
| Sources | ✅ From texts | ✅ Curated bibliography |

## Recommended Next Steps

### 1. Contact DHI for Academic Access (Priority)

The database was created with public funding (British Academy). As an academic project, Outremer may qualify for:
- Data export (CSV/XML/JSON)
- Research collaboration
- API access

**Email template:**
```
Subject: Academic data request: DHI Crusaders Database

Dear DHI Team,

I am working on the Outremer project (https://thodel.github.io/outremer/), 
a digital humanities initiative focused on crusader prosopography and 
authority file creation.

Your "Database of Crusaders to the Holy Land, 1095-1149" would be 
invaluable for our research. We're attempting to integrate multiple 
crusader databases into a unified knowledge graph.

Would it be possible to obtain a data export or establish research 
collaboration? We're happy to:
- Provide proper attribution
- Share our enriched data back
- Collaborate on future database development

Best regards,
[Name]
```

### 2. Browser-Based Scraping (Technical Workaround)

Use OpenClaw browser tool (when available) to:
- Log in with browser session
- Scrape via browser automation
- Export as it appears to be a legitimate user

This requires:
- Browser extension relay active
- Manual tab attachment
- Slower but undetectable

### 3. Alternative: Manual Curation

For high-value persons:
- Identify key persons in Outremer authority file
- Manually look up in DHI database via browser
- Add missing fields (gender, family, finance)
- Priority: persons with AUTH:CR* IDs

## Integration Plan (Once Data Obtained)

```bash
# 1. Run scraper (or import DHI export)
python scrapers/scrape_dhi_crusaders.py

# 2. Merge with existing authority file
python scripts/merge_dhi_authorities.py \
  --dhi data/dhi/dhi_crusaders_unified.json \
  --outremer scripts/outremer_index.json \
  --output scripts/outremer_index_merged.json

# 3. Update unified knowledge graph
python scripts/update_kg.py \
  --authorities scripts/outremer_index_merged.json \
  --output data/unified_kg.json
```

## Matching Strategy

DHI → Outremer matching by:
1. **Name variants** (normalized, case-insensitive)
2. **Expedition participation** (1st Crusade, 2nd Crusade)
3. **Toponym** (place of origin/title)
4. **Role** (Archbishop, Count, etc.)

Example match:
- DHI: "Achard unmarried of Marseilles" → Outremer: (no match yet - new person)
- DHI: "Fulk V of Anjou" → Outremer: AUTH:CR2 ✅

## Timeline

| Step | Effort | Priority |
|------|--------|----------|
| Contact DHI | 1 hour (email) | 🔴 High |
| Wait for response | 1-4 weeks | - |
| Browser scraping (if needed) | 4-8 hours | 🟡 Medium |
| Data integration | 2-4 hours | 🟢 Low (after data obtained) |

## Files Created

```
outremer/
├── scrapers/
│   ├── scrape_dhi_crusaders.py      # Main scraper
│   └── README_DHI_SCRAPER.md        # Documentation
├── data/dhi/
│   └── dhi_sample_output.json       # Sample mapped data
└── docs/
    └── DHI_INTEGRATION_NOTES.md     # This file
```

## Questions for Tobias

1. Do you have existing contacts at DHI Sheffield or with Jonathan Phillips/Alan Murray?
2. Should I draft the email request for data access?
3. Priority: focus on First Crusade only (1096-1099) or full 1095-1149 range?
4. Want me to try browser-based scraping via OpenClaw browser tool?
