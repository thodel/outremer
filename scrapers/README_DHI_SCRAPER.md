# DHI Crusaders Database Scraper

## Source

**Database:** A Database of Crusaders to the Holy Land, 1095-1149  
**URL:** https://www.dhi.ac.uk/crusaders/  
**Institution:** Digital Humanities Institute, University of Sheffield  
**Records:** ~1,100 crusaders from First Crusade (1096-1099) to Second Crusade (1145-1149)

## Status: ⚠️ Bot Protection Detected

The DHI website implements bot protection that returns HTTP 403 Forbidden for automated requests to person detail pages (`/person/?id=N`). The homepage and about pages are accessible, but individual person records are blocked.

### Evidence

```bash
$ curl -A "Mozilla/5.0..." "https://www.dhi.ac.uk/crusaders/person/?id=1"
# Returns: 403 Forbidden
```

### Workarounds Attempted

- ✅ Browser-like User-Agent headers
- ✅ Referer headers
- ✅ Session/cookie persistence
- ✅ Rate limiting (0.3-0.5s between requests)
- ❌ Direct scraping blocked

## Recommended Approaches

### Option 1: Contact DHI for Data Access (Recommended)

The database was created with public funding (British Academy, University of Leeds, Royal Holloway). Contact the DHI to request:
- Data export (CSV, XML, JSON)
- Research collaboration
- API access for academic purposes

**Contact points:**
- Digital Humanities Institute, University of Sheffield
- Prof. Jonathan Phillips (Royal Holloway) - original data compiler
- Dr. Alan Murray, Dr. Guy Perry (University of Leeds) - database harmonization

### Option 2: Manual Export via Browser

For small-scale extraction:
1. Use browser with scraper as browser extension
2. Use the OpenClaw browser tool (when available)
3. Export via "Print to PDF" → parse with OCR/NLP

### Option 3: Alternative Sources

Cross-reference with other crusader databases:
- **Foundation for Medieval Genealogy (MedLands)** - Already scraped ✅
- **Outremer authority file** - 126 persons (scripts/outremer_index.json)
- **Riley-Smith, "The First Crusaders, 1095-1131"** - Primary source
- **Phillips, "The Second Crusade"** - Primary source

## Data Model Mapping

The scraper maps DHI fields to the Outremer unified KG schema:

| DHI Field | Outremer KG Field | Notes |
|-----------|------------------|-------|
| Name (h1) | `names.preferred` | Full name as displayed |
| Country/Region | `places[]` (type: origin) | Modern country/region |
| Specific Title | `places[]` (type: title) | e.g., "Archbishop of Arles" |
| Role | `roles[]` | Parsed into role + type (lay/cleric) |
| Gender | `bio.gender` | Male/Female |
| Family | `relationships[]` | Parsed: brother, sister, etc. |
| Expedition | `expeditions[]` | e.g., "1st Crusade (1096-1099)" |
| Probability | `expeditions[].probability` | Certain/Probable/Possible |
| Consequences | `expeditions[].outcome` | Survived/Died/Returned |
| Actions | `expeditions[].actions` | Brief activity description |
| Contingent Leader | `expeditions[].leader` | Leader of contingent |
| Financial | `expeditions[].finance` | Mortgages, loans, etc. |
| Sources | `provenance.sources[]` | Primary source citations |

## Usage

```bash
cd /home/th/repos/outremer
source .venv/bin/activate

# Test single person (if accessible)
python scrapers/scrape_dhi_crusaders.py --single 1

# Discover valid person IDs (1 to N)
python scrapers/scrape_dhi_crusaders.py --discover 1500

# Full scrape (will fail if bot protection active)
python scrapers/scrape_dhi_crusaders.py
```

## Output Files

- `data/dhi/dhi_person_ids.json` - Cached list of valid person IDs
- `data/dhi/dhi_crusaders_raw.json` - Raw scraped data
- `data/dhi/dhi_crusaders_unified.json` - Mapped to Outremer KG schema

## Integration with Outremer KG

Once data is obtained, merge with existing authority file:

```bash
# Merge DHI data with outremer_index.json
python scripts/merge_authorities.py --source dhi --target outremer_index.json
```

## Notes on Data Quality

- DHI database uses modern English name forms (not Latin)
- Toponyms modernized (e.g., "Germany" not "Teutonic Kingdom")
- Participation probability assessed: Certain/Probable/Possible
- Sources cited in abbreviated form (full citations in Bibliography section)
- Family relationships explicitly stated when known

## License & Attribution

The DHI database is a pilot study with academic licensing. Any use of scraped data should:
1. Attribute the DHI and original compilers
2. Cite the database URL
3. Respect terms of use (contact DHI for clarification)

## TODO

- [ ] Contact DHI for data access
- [ ] Implement browser-based scraping via OpenClaw browser tool
- [ ] Add deduplication against existing Outremer authority file
- [ ] Create merge script for unified_kg.json integration
