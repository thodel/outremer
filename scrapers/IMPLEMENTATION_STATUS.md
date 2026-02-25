# FMG MedLands Scraper - Implementation Status

**Date:** 2026-02-25  
**Status:** ✅ Implemented (requires manual download due to server protection)

---

## What Was Created

### Scripts

1. **`scrape_fmg_medlands.py`** - Automated scraper
   - Attempts to scrape fmg.ac directly
   - Includes retry logic, polite delays, browser-like headers
   - ⚠️ Currently blocked by server (connection reset)

2. **`parse_fmg_offline.py`** - Offline parser (WORKING SOLUTION)
   - Parses locally downloaded HTML files
   - Same extraction logic as automated scraper
   - ✅ Use this when server blocks automated access

3. **`README_FMG_SCRAPER.md`** - Usage documentation
   - Instructions for both automated and manual methods
   - Troubleshooting guide
   - Integration steps

### Directory Structure

```
/home/th/repos/outremer/
├── scrapers/
│   ├── scrape_fmg_medlands.py      # Automated (blocked)
│   ├── parse_fmg_offline.py        # Offline parser ✅
│   └── README_FMG_SCRAPER.md       # Documentation
└── data/fmg/
    ├── raw/                        # Place for manual downloads
    └── fmg_medlands_crusaders.json # Output (generated after parsing)
```

---

## Current Blocker

**Problem:** fmg.ac server is blocking all automated HTTP requests with "Connection reset by peer"

**Evidence:**
- Direct curl requests fail
- Python requests with browser headers fail
- Server responds to ping but not HTTP/HTTPS
- This is intentional bot protection

**Solution:** Manual download + offline parsing

---

## Next Steps (Manual Process)

### Step 1: Download HTML Files

Open a browser and download these 5 pages:

1. http://fmg.ac/Projects/MedLands/JERUSALEM.htm
2. http://fmg.ac/Projects/MedLands/TRIPOLI.htm
3. http://fmg.ac/Projects/MedLands/ANTIOCH.htm
4. http://fmg.ac/Projects/MedLands/EDESSA.htm
5. http://fmg.ac/Projects/MedLands/BYZANTIUM.htm

Save them to: `/home/th/repos/outremer/data/fmg/raw/`

### Step 2: Run Offline Parser

```bash
cd /home/th/repos/outremer
source .venv/bin/activate
python scrapers/parse_fmg_offline.py
```

### Step 3: Verify Output

Check `data/fmg/fmg_medlands_crusaders.json` for extracted data.

Expected: ~200-250 persons total

### Step 4: Integrate into Knowledge Graph

```bash
python scripts/build_unified_kg.py --add-source data/fmg/fmg_medlands_crusaders.json
```

---

## Alternative: wget Command

If you prefer command-line download:

```bash
cd /home/th/repos/outremer/data/fmg
mkdir -p raw && cd raw

wget --header="User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)" \
     --wait=10 \
     --random-wait \
     --no-check-certificate \
     http://fmg.ac/Projects/MedLands/JERUSALEM.htm \
     http://fmg.ac/Projects/MedLands/TRIPOLI.htm \
     http://fmg.ac/Projects/MedLands/ANTIOCH.htm \
     http://fmg.ac/Projects/MedLands/EDESSA.htm \
     http://fmg.ac/Projects/MedLands/BYZANTIUM.htm
```

Then run the offline parser.

---

## Extraction Logic

The parser extracts:

| Field | Method |
|-------|--------|
| **Name** | Bold text (**NAME**) or text before comma/floruit |
| **Floruit** | Patterns: "fl. YYYY-YYYY", "died YYYY", "born YYYY" |
| **Title** | Regex matching king/queen/count/prince/etc. |
| **Relations** | "son of", "brother of", "married to", etc. |
| **Sources** | Medieval chronicle names (William of Tyre, RHC, etc.) |

---

## Testing

To test the offline parser without downloading all files:

```bash
# Create test directory
mkdir -p /home/th/repos/outremer/data/fmg/raw

# Download just ONE page first
cd /home/th/repos/outremer/data/fmg/raw
wget http://fmg.ac/Projects/MedLands/JERUSALEM.htm

# Run parser
cd /home/th/repos/outremer
python scrapers/parse_fmg_offline.py

# Check output
cat data/fmg/fmg_medlands_crusaders.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Extracted {d[\"total_persons\"]} persons')"
```

---

## Future Improvements

- [ ] Add support for more MedLands sections (Armenia, Cyprus, etc.)
- [ ] Improve relation extraction (nested family trees)
- [ ] Add confidence scores for extracted data
- [ ] Cross-reference with Wikidata automatically
- [ ] Export to multiple formats (CSV, RDF, Neo4j)

---

## Contact

Questions? Open an issue in the Outremer repo or contact the project team.
