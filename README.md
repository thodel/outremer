# People of the Medieval Levant — OUTREMER

[![CI](https://github.com/thodel/outremer/actions/workflows/Epic5-CI.yml/badge.svg?branch=main)](https://github.com/thodel/outremer/actions/workflows/Epic5-CI.yml)
[![Container](https://img.shields.io/badge/container-ghcr.io%2Fthodel%2Foutremer-blue)](https://github.com/thodel/outremer/pkgs/container/outremer)

A proof-of-concept pipeline for AI-assisted prosopography of the medieval Levant (Crusades era, 11th–14th centuries). Part of a collaborative research project by Jochen Burgtorf (Cal State Fullerton), Tobias Hodel (University of Bern), and Laura Morreale (Harvard / independent scholar).

> **Produktion:** <https://tei.dh.unibe.ch/outremer/> — läuft seit 2026-08-29
> auf `tei.dh.unibe.ch` im Uni-Netz. Die Extraktion nutzt dort GPUStack
> (`qwen3.8-27b`); ein Provenance-Gate verhindert, dass heuristischer
> Fallback-Output publiziert wird. Laufstatus maschinenlesbar unter
> [`data/status.json`](https://tei.dh.unibe.ch/outremer/data/status.json).
> Die GitHub-Pages-Ausgabe bleibt als offline gebaute Kopie bestehen.
>
> **Status:** proof of concept. The pipeline runs end-to-end. All LLM calls, recognition of scanned pages included, route through the local GPUStack instance at `gpustack.unibe.ch` — no third-party API key exists in the pipeline any more (the Mistral OCR fallback was removed in M17.2), and the nightly run on tei proves it every night by refusing every other outbound connection (see *Permitted network hosts*).

---

## Architecture

**Layer 1 — LLM extraction.** Reads historical texts (PDF or plain text) and extracts person-like signals: names, titles, epithets, roles, collective groups. Uses GPUStack-hosted models (`qwen3.8-27b` for extraction, `qwen3.8-27b` for scanned-PDF OCR, `minimax-m2.7` for orchestration). Falls back to heuristic regex NER when GPUStack is unavailable; a scanned page that the vision model cannot read stays empty and is reported as such — there is no external OCR fallback.

> **Which engine produced the published data.** Since 2026-08-29 the nightly
> run happens on `tei.dh.unibe.ch` inside the university network, where GPUStack
> is reachable, and a **provenance gate** refuses to publish anything the model
> did not produce (heuristic or mixed extraction, any fallback chunk, or a
> wrong model aborts the run before the commit). Both the tei site and the
> GitHub Pages copy therefore carry real model output; every document records
> its engine in `extraction_engine` (`gpustack` / `mixed` / `heuristic`, with
> chunk counts and the seed), and the run report aggregates it under
> `extraction.documents_by_engine`.
>
> GitHub-hosted runners still cannot reach GPUStack (every chunk `403`), so the
> Actions pipeline is `workflow_dispatch`-only — running it would regress the
> corpus to heuristic output. Before the tei move that degradation was the
> silent default, and until 2026-07-30 the output was labelled `gpustack`
> regardless.

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
│   ├── extract_persons.py         Layer 1: extraction via GPUStack or regex fallback
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

### Permitted network hosts

The pipeline is designed to run air-gapped except for the inference services
it is configured with.  The allow-list is **derived from the configuration**,
nothing else is ever contacted:

| Setting | Host on tei | Purpose |
|---|---|---|
| `GPUSTACK_BASE_URL` | `gpustack.unibe.ch` | LLM extraction and recognition of scanned pages (qwen3.8-27b) |
| `ATR_GATEWAY_URL` | the ATR gateway (idhefix) | ATR recognition engines (kraken, TrOCR), when configured |
| `MCP_BASE_URL` | `tei.dh.unibe.ch` | MCP federation candidates (M21.3), when configured and enabled |

Wikidata is reached only through the local snapshot (`WIKIDATA_SNAPSHOT`, #83);
with the guard on and no snapshot, reconciliation fails instead of calling
`query.wikidata.org`.

`run_pipeline.py --airgap` (or `OUTREMER_AIRGAP=1`) installs the guard from
`scripts/airgap.py` in the pipeline process **and** in the subprocesses it
starts: every outbound `connect()` to another host raises
`PermissionError: EGRESS BLOCKED …`, the document is reported as failed and
the run exits non-zero.  The tei nightly runs the whole corpus under this
guard (`deploy/tei/nightly.sh`), so a new outbound dependency introduced by
any future change fails the nightly and the provenance gate publishes nothing.

To add a host: declare it in `scripts/airgap.py` (`PERMITTED_URL_VARS`) and in
the table above in the same change.

- `tests/test_airgap.py` checks the guard offline (runs in CI).
- `python scripts/airgap_test.py --subset` runs one source end-to-end under the
  guard and fails on empty output; it needs GPUStack, so it runs on tei, not in CI.

### GPUStack configuration

Copy `.env.gpustack` template (or create manually):

```env
# All LLM calls route to GPUStack on gpustack.unibe.ch
GPUSTACK_BASE_URL=https://gpustack.unibe.ch/v1
GPUSTACK_API_KEY=your-token-here

# Optional local ATR recognition gateway
ATR_GATEWAY_URL=http://localhost:8200
ATR_API_KEY=your-gateway-token
ATR_HTTP_TIMEOUT=300

# Model names (check GPUStack dashboard for exact names)
# NB: qwen3-30b-a3b-instruct no longer exists on the stack (checked 2026-08-29)
EXTRACTION_MODEL=qwen3.8-27b
EXTRACTION_SEED=42
EXTRACTION_MAX_TOKENS=6000
# Qwen3 hybrids think silently until the budget is gone and return empty
# content unless plain-answer mode is forced:
EXTRACTION_DISABLE_THINKING=true
GPUSTACK_TIMEOUT=300
ORCHESTRATOR_MODEL=minimax-m2.7
QWEN3_VL_MODEL=qwen3.8-27b
# Same for recognition: in thinking mode qwen3.8-27b spends the whole
# OCR budget reasoning and returns empty text (both switches default on)
QWEN3_VL_DISABLE_THINKING=true

# OCR engine: qwen3-vl is the only value (the engine key is historical,
# the model behind it is QWEN3_VL_MODEL, qwen3.8-27b on GPUStack)
OCR_ENGINE=qwen3-vl

# Offline QID resolution (M17.1, #83). Path to the pre-1500 Wikidata snapshot
# built by thodel/wikidata_pre1500_mcp. Set, reconciliation runs without a
# single outbound request and records the snapshot's build date; unset, it
# falls back to query.wikidata.org and says so in the output.
WIKIDATA_SNAPSHOT=/home/dh/outremer/data/wd-pre1500.db
```

**Wikidata reconciliation, offline.** `scripts/wikidata_reconcile.py` resolved
every unseen name against `query.wikidata.org` — the last live network
dependency in the nightly, and a scorer that answered *Sanda Mihaela Popescu,
researcher* for the word "Popes". With `WIKIDATA_SNAPSHOT` set it resolves
against a local SQLite snapshot of every Wikidata human with a death date before
1500, including their aliases, which is what a charter actually spells
(*Albertus de Morra* for *Gregory VIII*). A name that matches nothing is written
as `status: "no_candidates"` rather than an empty list, so a miss can be told
from a name nobody looked up, and every entry carries the snapshot version it
was resolved against. The same snapshot is served to the rest of the DH fleet at
`/mcp/wd-pre1500/mcp`.

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
| `qwen3-vl` (the only engine) | GPUStack vision model, set by `QWEN3_VL_MODEL` (now `qwen3.8-27b`); an empty reading is reported, never papered over by another service | Fast | Free (local) |

The Mistral OCR fallback and its `MISTRAL_API_KEY` were removed (M14.2, M17.2):
no external API key can influence recognition.

**A scan that cannot be recognised fails loudly** (#72). When a PDF has no
usable text layer and GPUStack is unreachable, refuses, or returns no text,
the document is *not* written with empty text: it is listed under `failures`
in `data/staging/run_report.json` with the cause and what to check, and the
run exits 1. A short text PDF without a page image keeps its text.

Output: `site/data/*.json`, `site/bib/*.bib`, `bib/*.bib`.

Every processed document also produces a canonical evidence-first artifact at
`data/evidence/<document-id>.evidence.json`. These records separate immutable
source snapshots and passages from extracted mentions, assertions, identity
hypotheses, and generation provenance. They are validated against the
evidence-first JSON Schema and SHACL shapes before being published. Invalid
canonical output fails the document run; the existing `site/data` JSON remains
available as a temporary compatibility format.

The pipeline mirrors validated artifacts to `site/evidence/` for the unified
Explorer. Select a document in `site/explorer.html` to review source passages,
assertions, identity hypotheses, candidate scores, and generation provenance
beside the legacy link review. Documents without an evidence artifact continue
to use the legacy interface. `site/evidence-review.html` remains available as a
compatibility entry point and uses the same renderer and local review store.

### With Docker

Version tags publish an image to `ghcr.io/thodel/outremer`. It carries the
pipeline, not the corpus: mount the PDFs to process and a folder for the
output, and pass the backend settings as an env file.

```bash
docker run --rm --env-file .env.gpustack \
  -v "$PWD/pdfs:/app/data/raw:ro" -v "$PWD/site:/app/site" \
  ghcr.io/thodel/outremer:latest
```

Without a reachable GPUStack the run still completes, but degraded: recognition
yields no text and extraction falls back to heuristic NER. Both are logged, and
the run report records it.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests -q
```

## Evaluation

The `evaluation/` package measures pipeline quality against gold fixtures,
so prompt/model changes are judged by numbers rather than impressions.
Gold is seeded from Human-in-the-Loop adjudications (`data/decisions.json`):
scholar decisions become regression tests.

```bash
# Score the committed fixture snapshots (offline; also runs in CI)
python -m evaluation.harness

# Score the *current* site/data output — run after a pipeline change
python -m evaluation.harness --live

# Regenerate fixtures after new adjudications arrive
python -m evaluation.build_fixture
```

**Extraction quality** is measured separately, against the full-gold fixture
(`mode: "full"`, currently munro only, DRAFT pending scholar validation).
Because CI cannot reach GPUStack, this scores the **heuristic extractor** — the
engine that actually produces the published corpus. Rewriting it on 2026-07-30
moved munro from P 0.047 / R 0.318 / F1 0.082 to **P 0.568 / R 0.955 /
F1 0.712** (individual persons only; collectives are excluded from the person
gold by design and scored separately). Recall is now the strong side: 21 of 22
gold persons are found. Measuring Qwen3 itself needs a run from inside the
university network.

Key metric: **linking agreement** — of the pairs scholars reviewed, how
many does the responsible system's top proposal agree with. Adjudications
cover two systems, each judged against its own output: the authority-file
linker (`AUTH:CR…` ids) and Wikidata reconciliation (`wikidata:Q…` ids).
Baseline 2026-10-09 after the M19.0 gold repair (#97) and the floor
re-sweep (`evaluation/baselines/epic19-post-repair.json`): authority
**0.9828 over 58 pairs** (4 accepts, all hit at 1.00; 54 rejects, 1 still
proposed), Wikidata 0.8125 over 16 — see the caveat below. CI evaluates
with `--relink`: the linker in the checkout is run over the fixtures'
extracted persons, so the gate measures code, not the nightly's snapshot.
The 2026-07-18 figure (combined 0.9155, authority 0.8909) is superseded: six
of its seven authority accepts named the wrong person (#98), and the +0.018
lift it showed over a null linker was carried entirely by those wrong
matches.

> **Read agreement against the null baseline, not on its own.** Agreement
> rewards proposing what scholars accepted *and* not proposing what they
> rejected. With 4 accepts against 54 rejects a linker that proposes
> **nothing at all** scores 54/58 = **0.931** on authority. The harness
> therefore reports `null`, `lift`, and `accept_rate` per system, and CI
> gates on `--min-lift` against the *weakest* segment; a combined threshold
> cannot fail, because Wikidata's accept-only gold masks any authority
> collapse. Four positive examples are not a measurement of linker quality —
> gold growth (#36, Part 2 of `docs/AUTHORITY_REVIEW_WORKSHEET.md`) is what
> makes the authority figure mean something.

> **Wikidata 0.8125, not 1.0.** The fixtures now carry the offline resolver's
> answers (#83/#147). Three of sixteen accepted QIDs are no longer the top
> candidate: *Baldwin of Ibelin* (Q804832, d. 1187) ties with his namesake
> Q2891991 (d. 1313) at 1.00 and loses the tie; *Muhammad* (Q9458) ties with
> a Bavand ruler of the same name (Q16202005); *Ibrahim* (Q1768161) is outside
> the pre-1500 snapshot and resolves to the caliph Ibrahim ibn al-Walid
> (Q128416). Label-equal ties need a date or context tiebreak; tracked
> separately.

Where a backend does not honour `EXTRACTION_SEED`, generate repeated live
outputs and evaluate them as a band:

```bash
python -m evaluation.harness --live --repeat 5 \
  --repeat-command "python scripts/run_pipeline.py"
```

Repeated gates use the lowest observed agreement, not the mean, so sampling
variance cannot make a regression appear to pass.

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
6. **Export decisions** downloads adjudications as `outremer-decisions-YYYY-MM-DD.json`.

Decisions are persisted in browser `localStorage` — survive page refreshes, scoped per-document.

**From export to pipeline impact — the feedback round-trip:**

Scholar decisions flow back into the pipeline via a JSON file that the pipeline reads on the next run:

```
Explorer review → [Export decisions JSON] → data/decisions.json → pipeline run → entity_feedback.json
```

**Steps to close the loop:**

1. In the Explorer, click **Export decisions** — a file like `outremer-decisions-2026-07-10.json` downloads.
2. Save it to the repo as `data/decisions.json` (or any path you pass with `--review-decisions-path`).
3. Run the pipeline with both flags:

   ```bash
   python scripts/run_pipeline.py --input-dir data/raw \
     --entity-feedback-path data/entity_feedback.json \
     --review-decisions-path data/decisions.json
   ```

4. The pipeline will:
   - Validate the decisions file (aborts with a clear error report if the schema is invalid).
   - Tally accept/reject votes per name (cross-reviewer deduplication is automatic).
   - Move names with ≥2 reject votes from different reviewers into `blocked_terms`.
   - Move names with ≥1 accept vote (and accept ≥ reject) into `allow_terms`.
   - Write the updated `data/entity_feedback.json`.

**Validation before running:**

Catch schema errors before the pipeline runs:

```bash
python3 -m scripts.validate_decisions data/decisions.json
```

Valid decisions show `✅  N entries, N valid, 0 errors`. Invalid files abort with a line-by-line error report.

**Conflict detection:**

If two different reviewers disagree on the same person in the same document (one accept, one reject), the pipeline logs a conflict warning. Conflicts do not block processing — the vote threshold determines the outcome.

**Schema for decisions.json:**

```json
[
  {
    "doc_id":     "rileysmith-motivesearliestcrusaders-1983-92cc17aaccd3",
    "person":     "Baldwin I",
    "decision":   "accept",          // accept | reject | not_a_person | wrong_era | is_group
    "client_id":  "anon-abc123xyz",  // optional, auto-generated per browser
    "comment":    "confirmed match", // optional
    "submitted_at": "2026-07-10T09:00:00Z"  // optional, ISO 8601
  }
]
```

Accept/reject votes are aggregated **per normalised name** across all entries with the same `doc_id + person`. The canonical name stored in `entity_feedback.json` is taken from the first occurrence.

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
