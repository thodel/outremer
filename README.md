# People of the Medieval Levant — Outremer PoC

A proof-of-concept pipeline for AI-assisted prosopography of the medieval Levant (Crusades era, 11th–14th centuries). Part of a collaborative research project by Jochen Burgtorf (Cal State Fullerton), Tobias Hodel (University of Bern), and Laura Morreale (Harvard / independent scholar).

> **Status:** proof of concept. The pipeline runs end-to-end; accuracy improves substantially with a Gemini API key and grows further through iterative Human-in-the-Loop review.

---

## What this does

Traditional crusades prosopography focuses on elites — kings, bishops, military orders. This project asks: can generative AI + Knowledge Graphs make the *full* population of the medieval Levant visible at scale, including refugees, artisans, women, unnamed groups, and non-Latin actors?

The pipeline implements a two-layer architecture:

| Layer | What it does |
|---|---|
| **Layer 1 — LLM extraction** | Reads historical texts (PDF or plain text) and extracts *person-like signals*: names, titles, epithets, roles, collective groups. Uses Google Gemini (`gemini-2.0-flash`) with a structured JSON prompt; falls back to heuristic regex NER when no API key is set. |
| **Layer 2 — KG linking** | Fuzzy-matches extracted mentions against a curated authority file of 126 known crusader persons (sourced from an Omeka database). Returns ranked candidates with confidence scores and flags ambiguous or multi-candidate matches. |

Results are published as a static GitHub Pages site with a **Human-in-the-Loop review UI** — scholars can accept, reject, or flag individual candidate links and export their decisions as JSON.

---

## Repository structure

```
outremer/
├── data/raw/           Source texts (.pdf, .txt) to process
├── bib/                BibTeX output (repo copy)
├── scripts/
│   ├── run_pipeline.py         Main pipeline entry point
│   ├── extract_persons_google.py  Layer 1: Gemini + fallback extraction
│   └── outremer_index.json     Authority file (126 crusader persons)
├── site/               Static site (deployed to GitHub Pages)
│   ├── index.html
│   ├── app.js          Explorer + H-i-t-L adjudication UI
│   ├── style.css
│   ├── data/           Generated per-document JSON
│   └── bib/            Generated BibTeX (site copy)
├── .github/workflows/
│   ├── pipeline.yml    Runs extraction + linking on push / nightly
│   └── pages.yml       Deploys site/ to GitHub Pages
├── requirements.txt
└── README.md
```

---

## Setup (local)

```bash
git clone https://github.com/thodel/outremer.git
cd outremer

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## Configuration

| Variable | Where | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | env var or `.env` file | Activates Gemini extraction. Without it, the pipeline falls back to heuristic regex NER (lower recall, confidence ≈ 0.30). |

For GitHub Actions, add the key under **Settings → Secrets and variables → Actions** as `GOOGLE_API_KEY`.

---

## Running the pipeline

```bash
# Activate venv first
source .venv/bin/activate

# With Gemini (recommended)
export GOOGLE_API_KEY=your_key_here
python scripts/run_pipeline.py --input-dir data/raw --genai-metadata

# Without API key (heuristic fallback)
python scripts/run_pipeline.py --input-dir data/raw

# All options
python scripts/run_pipeline.py --help
```

Output is written to `site/data/*.json`, `site/bib/*.bib`, and `bib/*.bib`.

---

## Reviewing results

**GitHub Pages:** The site is auto-deployed on every push to `main`. Visit `https://thodel.github.io/outremer/`.

**Locally:**
```bash
cd site
python3 -m http.server 8080
# open http://localhost:8080
```

**H-i-t-L workflow:**

1. Select a document from the dropdown and click **Load**.
2. The **Extracted Persons** panel lists all detected mentions with confidence scores.
3. The **Links** panel shows candidate matches ranked by fuzzy score (green = high, yellow = medium, red = low).
4. For each candidate, click **✅ Accept**, **❌ Reject**, or **🚩 Flag**. Add an optional comment.
5. Use the filter bar to focus on unreviewed or flagged items.
6. Click **Export decisions** to download your adjudications as a JSON file.

Decisions are persisted in the browser's `localStorage` — they survive page refreshes and are scoped per-document.

---

## Authority file

`scripts/outremer_index.json` is a gold person authority file containing 126 crusader-era persons. Each entry includes:

- `authority_id` — unique identifier (e.g. `AUTH:CR1`)
- `preferred_label` — canonical name
- `variants` — alternate spellings and forms
- `normalized` — pre-computed lowercase/accent-stripped forms for matching
- `name` — parsed name components (given, toponym, regnal, epithet)
- `identifiers.omeka_item_id` — link to source Omeka database record
- `provenance.source_files` — Omeka XML source files

The linker matches against all variant forms using `rapidfuzz` token-sort ratio (≥ 60% to appear as a candidate; ≥ 90% = "high confidence").

---

## GitHub Actions

| Workflow | Trigger | What it does |
|---|---|---|
| `pipeline.yml` | push to `main`, nightly 02:00 UTC, manual | Runs `run_pipeline.py --genai-metadata`, commits updated `site/data/`, `site/bib/`, `bib/` back to `main` |
| `pages.yml` | push to `main`, manual | Deploys `site/` to GitHub Pages |

---

## Project context

*People of the Medieval Levant* is a collaborative digital humanities project exploring how generative AI and Knowledge Graphs can enable a more inclusive prosopography of the Crusades era — one that goes beyond the traditional elite focus to encompass non-Western actors, women, refugees, artisans, and unnamed collectives.

The project is led by **Jochen Burgtorf** (medieval history), **Tobias Hodel** (digital humanities / AI), and **Laura Morreale** (medieval cultural contact). A book chapter co-authored by Burgtorf and Hodel outlines the theoretical framework; this repository is the technical proof of concept.

The pipeline treats ambiguity as data rather than error. Mismatches between the LLM layer and the KG layer are diagnostic signals — they reveal name collisions, missing entities, or outdated assumptions. Scholarly adjudication through the H-i-t-L interface is where historical interpretation happens.
