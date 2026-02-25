# FMG MedLands Scraper

## Overview

This scraper extracts crusader nobility data from the Foundation for Medieval Genealogy's MedLands project.

**Target URL:** http://fmg.ac/Projects/MedLands/

## Usage

### Automated Scraping (may be blocked)

```bash
cd /home/th/repos/outremer
source .venv/bin/activate
python scrapers/scrape_fmg_medlands.py
```

**Output:** `data/fmg/fmg_medlands_crusaders.json`

### ⚠️ If Automated Scraping Fails

The fmg.ac server often blocks automated requests. If you see "Connection reset by peer" errors:

#### Option 1: Manual Download + Local Parsing

1. **Download pages manually** in your browser:
   - http://fmg.ac/Projects/MedLands/JERUSALEM.htm
   - http://fmg.ac/Projects/MedLands/TRIPOLI.htm
   - http://fmg.ac/Projects/MedLands/ANTIOCH.htm
   - http://fmg.ac/Projects/MedLands/EDESSA.htm
   - http://fmg.ac/Projects/MedLands/BYZANTIUM.htm

2. **Save to local directory:**
   ```bash
   mkdir -p /home/th/repos/outremer/data/fmg/raw
   # Save each page as: raw/JERUSALEM.htm, raw/TRIPOLI.htm, etc.
   ```

3. **Run offline parser:**
   ```bash
   python scrapers/scrape_fmg_medlands.py --offline
   ```

#### Option 2: Use wget with Browser Headers

```bash
cd /home/th/repos/outremer/data/fmg
wget --header="User-Agent: Mozilla/5.0" \
     --wait=5 \
     --random-wait \
     http://fmg.ac/Projects/MedLands/JERUSALEM.htm \
     http://fmg.ac/Projects/MedLands/TRIPOLI.htm \
     http://fmg.ac/Projects/MedLands/ANTIOCH.htm \
     http://fmg.ac/Projects/MedLands/EDESSA.htm \
     http://fmg.ac/Projects/MedLands/BYZANTIUM.htm
```

Then parse locally.

## Target Data

The scraper extracts:
- **Name** (person's full name)
- **Floruit** (active dates, e.g., "1100-1118")
- **Title** (King, Count, Prince, etc.)
- **Relations** (family connections mentioned)
- **Sources** (medieval chronicles referenced)
- **Metadata** (source URL, region, scrape timestamp)

## Expected Yield

- **Kings of Jerusalem:** ~50 persons
- **Counts of Tripoli:** ~30 persons
- **Princes of Antioch:** ~25 persons
- **Counts of Edessa:** ~20 persons
- **Byzantine Emperors:** ~100 persons

**Total:** ~200-250 crusader nobility entries

## Integration

Once generated, integrate into the unified knowledge graph:

```bash
cd /home/th/repos/outremer
python scripts/build_unified_kg.py --add-source data/fmg/fmg_medlands_crusaders.json
```

## Troubleshooting

### "Connection reset by peer"
- Server is blocking automated requests
- Use manual download method (Option 1 above)
- Wait a few hours and try again

### "403 Forbidden"
- Same as above - server protection
- Try from different IP or use Tor
- Manual download is most reliable

### Empty output file
- Check that HTML files were actually downloaded
- Verify BeautifulSoup is parsing correctly
- MedLands HTML structure may have changed

## License & Ethics

- MedLands content is © Foundation for Medieval Genealogy
- This scraper is for **research purposes only**
- Always respect robots.txt and rate limits
- Consider contacting fmg.ac for collaboration/data sharing

## Contact

For questions or improvements, open an issue in the Outremer repo.
