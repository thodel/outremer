# People of the Medieval Levant — OUTREMER

A proof-of-concept pipeline for AI-assisted prosopography of the medieval Levant (Crusades era, 11th–14th centuries). Part of a collaborative research project by Jochen Burgtorf (Cal State Fullerton), Tobias Hodel (University of Bern), and Laura Morreale (Harvard / independent scholar).

> **Status:** proof of concept. The pipeline runs end-to-end. All LLM calls route through the local GPUStack instance at `tei.dh.unibe.ch` — no external API calls to Google, Mistral, or third-party LLM providers.

---

## Architecture

**Layer 1 — LLM extraction.** Reads historical texts (PDF or plain text) and extracts person-like signals: names, titles, epithets, roles, collective groups. Uses GPUStack-hosted models (Qwen3-30B-A3B for extraction, MiniMax-M2.7 for orchestration). Falls back to local EasyOCR for scanned PDFs and heuristic regex NER when GPUStack is unavailable.

**Layer 2 — KG linking.** Fuzzy-matches extracted mentions against a curated authority file of known crusader persons. Returns ranked candidates with confidence scores and flags ambiguous or multi-candidate matches.

Results are published as a static GitHub Pages site with a **Human-in-the-Loop review UI** — scholars can accept, reject, or flag individual candidate links and export their decisions as JSON.

---

## Repository structure

```
outremer/
├── data/
│   ├── raw/                       Source texts (.pdf, .txt)
│   ├── peerage_pre1500_export/    Wikidata peerage data (pre-1500 persons)
│   ├── entity_feedback.json       Filtered noisy entities
│   └── decisions.json             Human adjudication decisions
├── scripts/
│   ├── config.py                  GPUStack configuration (reads .env.gpustack)
│   ├── llm_client.py              Thin OpenAI-compatible GPUStack client
│   ├── run_pipeline.py            Main pipeline entry point
│   ├── extract_persons_google.py  Layer 1: extraction via GPUStack or regex fallback
│   ├── wikidata_reconcile.py      Layer 2: KG linking
│   ├── export_peerage_pre1500.py  Wikidata peerage export (QID → CSV)
│   └── install-triplestore.sh     Canonical Fuseki/GraphDB installer
├── scrapers/                      Historical web scrapers
├── bib/                           BibTeX output
├── docs/                          Living documentation
│   ├── LOCAL_LLM_ADAPTATION_PLAN.md   Full Epic 1–8 roadmap
│   ├── EPIC4_HBLS_MCP.md              HBLS MCP server docs
│   └── archive/                       Stale/historical docs
├── site/                          Static site (deployed to GitHub Pages)
│   ├── index.html
│   ├── app.js                     Explorer + H-i-t-L adjudication UI
│   └── data/                      Generated per-document JSON
├── .github/workflows/
│   ├── pipeline.yml               Runs extraction + linking on push / nightly
│   └── pages.yml                  Deploys site/ to GitHub Pages
├── requirements.txt
└── README.md
```

---

## Setup

```bash
git clone https://github.com/thodel/outremer.git
cd outremer

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### GPUStack configuration

Copy `.env.gpustack` template (or create manually):

```env
# All LLM calls route to GPUStack on tei.dh.unibe.ch
GPUSTACK_BASE_URL=https://tei.dh.unibe.ch/v1
GPUSTACK_API_KEY=your-token-here

# Model names (check GPUStack dashboard for exact names)
EXTRACTION_MODEL=qwen3-30b-a3b-instruct
ORCHESTRATOR_MODEL=minimax-m2.7

# OCR engine: easyocr (local CPU/GPU, no API call) or gpustack (MiniMax-M2.7)
OCR_ENGINE=easyocr
```

`.env.gpustack` is git-ignored. Without it, `config.py` uses sensible defaults (tei endpoint, no API key required for public models).

---

## Running the pipeline

```bash
source .venv/bin/activate

# Standard run (uses .env.gpustack if present)
python scripts/run_pipeline.py --input-dir data/raw

# With GPUStack API key
export GPUSTACK_API_KEY=your-token
python scripts/run_pipeline.py --input-dir data/raw

# Language hint for multilingual sources
python scripts/run_pipeline.py --input-dir data/raw --language la    # Latin
python scripts/run_pipeline.py --input-dir data/raw --language ar    # Arabic
# Supported: la, fro (Old French), ar, el (Greek), de (Middle High German)

# Sync human adjudication into feedback memory
python scripts/run_pipeline.py --input-dir data/raw \
  --entity-feedback-path data/entity_feedback.json \
  --review-decisions-path data/decisions.json

# All options
python scripts/run_pipeline.py --help
```

**OCR engines:**

| Engine | How it works | Speed | Cost |
|---|---|---|---|
| `easyocr` (default) | Local CPU/GPU, no API call | Medium | Free |
| `gpustack` | GPUStack MiniMax-M2.7 | Fast | Free (local) |
| `mistral` | Mistral API (legacy, requires `MISTRAL_API_KEY`) | Fast | Paid |

Output: `site/data/*.json`, `site/bib/*.bib`, `bib/*.bib`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests -q
```

---

## Reviewing results

**GitHub Pages:** Auto-deployed on every push to `main`. `https://thodel.github.io/outremer/`

**Locally:**
```bash
cd site && python3 -m http.server 8080
# open http://localhost:8080
```

**H-i-t-L workflow:**

1. Select a document from the dropdown and click **Load**.
2. **Extracted Persons** panel lists all detected mentions with confidence scores.
3. **Links** panel shows candidate matches ranked by fuzzy score (green = high, yellow = medium, red = low).
4. Click **✅ Accept**, **❌ Reject**, or **🚩 Flag** for each candidate.
5. Filter bar focuses on unreviewed or flagged items.
6. **Export decisions** downloads adjudications as JSON.

Decisions are persisted in browser `localStorage` — survive page refreshes, scoped per-document.

---

## Authority file

`scripts/outremer_index.json` contains curated gold-standard person entries. Each entry:

- `authority_id` — unique identifier (e.g. `AUTH:CR1`)
- `preferred_label` — canonical name
- `variants` — alternate spellings and forms
- `normalized` — pre-computed lowercase/accent-stripped forms
- `name` — parsed name components (given, toponym, regnal, epithet)
- `provenance.source_files` — source attribution

The linker matches against all variant forms using `rapidfuzz` token-sort ratio (≥ 60% = candidate; ≥ 90% = high confidence).

---

## HBLS MCP Integration

The HBLS (Historisches Biographisches Lexikon der Schweiz) MCP server runs on tei at `http://localhost:8003`. Use it to cross-reference extracted persons against HBLS biographical data:

```bash
# Quick check
curl "http://localhost:8003/mcp/search?q=Habsburg&limit=3"

# Full API reference
curl "http://localhost:8003/mcp"
```

See `docs/EPIC4_HBLS_MCP.md` for full API reference.

---

## GitHub Actions

| Workflow | Trigger | What it does |
|---|---|---|
| `pipeline.yml` | push to `main`, nightly 02:00 UTC, manual | Runs `run_pipeline.py`, commits `site/data/`, `site/bib/` back to `main` |
| `pages.yml` | push to `main`, manual | Deploys `site/` to GitHub Pages |

For `pipeline.yml` secrets, add `GPUSTACK_API_KEY` under **Settings → Secrets and variables → Actions**.

---

## Project context

*People of the Medieval Levant* is a collaborative digital humanities project exploring how generative AI and Knowledge Graphs can enable a more inclusive prosopography of the Crusades era — one that goes beyond the traditional elite focus to encompass non-Western actors, women, refugees, artisans, and unnamed collectives.

Led by **Jochen Burgtorf** (medieval history), **Tobias Hodel** (digital humanities / AI), and **Laura Morreale** (medieval cultural contact).

The pipeline treats ambiguity as data rather than error. Mismatches between the LLM layer and the KG layer are diagnostic signals — they reveal name collisions, missing entities, or outdated assumptions. Scholarly adjudication through the H-i-t-L interface is where historical interpretation happens.