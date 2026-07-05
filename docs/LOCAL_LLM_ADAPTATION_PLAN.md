# OUTREMER — Project Improvement Plan

**Author:** DH bot (via OpenClaw)  
**Date:** 2026-07-05  
**Status:** Draft — for review

---

## Executive Summary

The current pipeline depends on two proprietary APIs: **Google Gemini** (person extraction) and **Mistral** (OCR). This plan covers:

1. **Replacing both with local/open models** (Ollama, LM Studio, vLLM, or MiniMax self-hosted)
2. **Improving the overall project** across KG quality, pipeline reliability, scrapers, and UI

---

## EPIC 1 — LLM Provider Abstraction  ⚠️ HIGH PRIORITY

**Goal:** Replace `google-genai` and `mistralai` hardcoded calls with a swappable config layer, so the pipeline runs entirely offline on locally hosted models.

### Rationale

- Proprietary APIs cost money and require internet access
- MiniMax, Qwen3, and GPT-OSS models now match or exceed Gemini 2.0-flash on medieval multilingual tasks
- The pipeline should work on a laptop in a archive basement

### MILESTONE 1.1 — Config Layer

**Files:** `scripts/config.py`, `.env.example`

Add a provider switch:

```env
# LLM provider for person extraction (gemini | openai | ollama | lmstudio | vllm)
EXTRACTION_PROVIDER=ollama
EXTRACTION_MODEL=qwen3:latest
EXTRACTION_BASE_URL=http://localhost:11434/v1
EXTRACTION_API_KEY=   # empty for local

# OCR engine (mistral | easyocr | tesseract)
OCR_ENGINE=tesseract
MISTRAL_API_KEY=   # only needed if OCR_ENGINE=mistral
```

**Acceptance:** Provider + model + base URL configurable via env vars only; no code changes needed to switch providers.

---

### MILESTONE 1.2 — LLMClient ABC + Ollama Implementation

**File:** `scripts/llm_client.py` (new)

```python
from abc import ABC, abstractmethod

class LLMClient(ABC):
    @abstractmethod
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Send prompt to LLM, return raw string response."""
        ...

    @abstractmethod
    def name(self) -> str:
        ...

class OllamaClient(LLMClient):
    def __init__(self, model: str, base_url: str = "http://localhost:11434/v1"):
        ...

class LMStudioClient(LLMClient):
    # OpenAI-compatible endpoint
    ...

class VLLMClient(LLMClient):
    # OpenAI-compatible endpoint (supports Qwen, Llama, Mistral)
    ...

class GoogleClient(LLMClient):
    # Current: google.genai
    ...
```

**Decision:** All local implementations use the **OpenAI-compatible `/v1/chat/completions` interface**. Ollama, LM Studio, and vLLM all expose this. MiniMax and GPT-OSS also expose OpenAI-compatible endpoints. One `openai.OpenAI` client handles all of them.

**Acceptance:** `llm_client.get_client()` returns a client for the configured `EXTRACTION_PROVIDER`. All existing `extract_persons_google.py` calls replaced with this.

---

### MILESTONE 1.3 — Mistral OCR → Local OCR Fallback

**File:** `scripts/run_pipeline.py` — refactor `_mistral_ocr()`

```python
def _ocr_image(path: Path) -> str:
    engine = os.environ.get("OCR_ENGINE", "easyocr")
    if engine == "easyocr":
        return _easyocr(path)
    elif engine == "tesseract":
        return _tesseract_ocr(path)
    elif engine == "mistral":
        return _mistral_ocr(path)   # existing
    else:
        raise ValueError(f"Unknown OCR_ENGINE: {engine}")
```

**EasyOCR setup:**
```python
import easyocr
reader = easyocr.Reader(['la', 'en', 'fr', 'de', 'it', 'es'], gpu=True)
results = reader.readtext(path.read_bytes())
text = " ".join(r[1] for r in results)
```

**Acceptance:** Switching `OCR_ENGINE=easyocr` produces comparable text quality to Mistral on medieval Latin/Old French charters. Measured by person extraction recall on a benchmark document.

---

### MILESTONE 1.4 — Prompt Tuning for Local Models

**File:** `scripts/extract_persons_google.py`

Changes needed for Qwen3 / local models:

| Issue | Fix |
|---|---|
| Emoji in prompt (🚫 ✅ 📋) confuse some models | Replace with ASCII: `[EXCLUDE]`, `[INCLUDE]`, `[FORMAT]` |
| Gemini-specific JSON framing | Remove `Respond with EXACTLY this JSON`; use `Output valid JSON only. No markdown fences.` |
| Very large `_CHUNK_SIZE` (5,500) | Tune per model: test at 3k, 5k, 8k chars; measure truncation rate |
| `gemini-2.0-flash` hardcoded | Remove; use config-driven model name |

**Test document:** One Latin charter and one Old French chronicle. Run extraction with Ollama Qwen3 and compare:
- Person count
- Metadata completeness
- BibTeX quality

**Acceptance:** Delta < 10% on all three metrics vs Gemini baseline on same documents.

---

### MILESTONE 1.5 — Smoke Test Suite

**File:** `scripts/test_llm_client.py` (new)

```bash
# Test all providers
python scripts/test_llm_client.py --provider ollama --model qwen3:latest
python scripts/test_llm_client.py --provider lmstudio --model qwen3
python scripts/test_llm_client.py --provider openai --model minimax-m2.7

# Run full pipeline with each
python scripts/run_pipeline.py --input-dir data/raw --provider ollama
```

**Acceptance:** All three providers produce valid output on the benchmark document set.

---

## EPIC 2 — Pipeline Reliability

### MILESTONE 2.1 — JSON Recovery on Malformed LLM Output

**Problem:** Local models sometimes output markdown fences or extra text around JSON. Current parser dies.

**Fix in `scripts/extract_persons_google.py`:**

```python
def _parse_llm_json(raw: str) -> dict | None:
    """Extract JSON from LLM output, even with markdown fences or extra text."""
    # Try direct parse first
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass
    # Strip markdown fences
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'```\s*$', '', raw, flags=re.MULTILINE)
    # Find first { and last }
    start = raw.find('{')
    end = raw.rfind('}') + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError:
            pass
    return None
```

**Acceptance:** 95% of LLM outputs parse successfully after recovery attempts.

---

### MILESTONE 2.2 — Chunk Boundary Respect

**Problem:** `_chunk_text()` splits mid-sentence, losing context for the LLM.

**Fix:** Split only on double newlines or sentence boundaries:

```python
def _chunk_text(text: str, size: int = 5500) -> list[tuple[int, str]]:
    """Split on paragraph/sentence boundaries, not mid-word."""
    paragraphs = text.split('\n\n')
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) <= size:
            current += para + '\n\n'
        else:
            if current:
                chunks.append((text.index(current), current.strip()))
            current = para + '\n\n'
    if current:
        chunks.append((text.index(current), current.strip()))
    return chunks
```

---

### MILESTONE 2.3 — Retry with Exponential Backoff

```python
import time, functools

def with_retry(fn, max_attempts=3, base_delay=2.0):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        for attempt in range(max_attempts):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(base_delay * (2 ** attempt))
                logger.warning(f"Retry {attempt+1}/{max_attempts}: {e}")
    return wrapper
```

Apply to: LLM calls, Wikidata SPARQL queries, Mistral OCR.

---

### MILESTONE 2.4 — Pipeline Run Reports

**File:** `scripts/run_pipeline.py` — after each run, write `data/staging/run_report.json`:

```json
{
  "run_at": "2026-07-05T18:00:00Z",
  "docs_total": 12,
  "docs_ok": 10,
  "docs_failed": 2,
  "total_persons": 347,
  "llm_provider": "ollama",
  "model": "qwen3:latest",
  "ocr_engine": "easyocr",
  "failures": [
    {"doc": "henri1_charter", "error": "LLM timeout", "retry": 3}
  ]
}
```

---

## EPIC 3 — KG Enrichment & Authority Quality

### MILESTONE 3.1 — Wikidata QID Enrichment (0 → 19k links)

**Current state:** 0 Wikidata links in `unified_kg.json` despite 23k+ Wikidata persons being in the peerage export.

**Root cause:** `build_unified_kg.py` does exact normalized name matching only. Most names don't match exactly across sources.

**Fix — fuzzy matching + occupation filter:**

```python
from rapidfuzz import fuzz

def match_wikidata_to_authority(auth_persons, wikidata_persons, threshold=85):
    """Match authority persons to Wikidata using fuzzy string matching."""
    for auth_id, person in auth_persons.items():
        name = person["preferred_label"]
        for qid, wd_person in wikidata_persons.items():
            score = fuzz.token_sort_ratio(name, wd_person["preferred_label"])
            if score >= threshold:
                person["identifiers"]["wikidata_qid"] = qid
                break
```

**Acceptance:** ≥50% of the 126 authority persons get a `wikidata_qid` link.

---

### MILESTONE 3.2 — Gender字段 Completion

**Current:** Most Wikidata persons have `gender: unknown`.

**Fix:** Parse P21 (sex or gender) from Wikidata CSV data in `build_unified_kg.py` — it's already being parsed in `load_wikidata_peerage()` but not populating the field correctly.

---

### MILESTONE 3.3 — Relationship Cleanup

**Problem:** Wikidata relationship parsing (P22, P25, P26, P40) creates duplicate or malformed entries.

**Fix:** Add deduplication and canonicalization step after loading Wikidata:

```python
def clean_relationships(person: dict) -> dict:
    seen = set()
    cleaned = []
    for rel in person.get("relationships", []):
        key = (rel.get("type"), rel.get("person_label", "").lower())
        if key not in seen:
            seen.add(key)
            cleaned.append(rel)
    person["relationships"] = cleaned
    return person
```

---

### MILESTONE 3.4 — Arabic / Latin Source Coverage

**Goal:** Expand beyond the current ~126-person SDHSS authority to include:
- Muslim elites (Saladin's court, Ayyubid dynasty, Mamluk sultans)
- Byzantine figures
- Local Levantine Christians (Melkite, Syrian Orthodox, Armenian)

**Action:** Create `scripts/authority_arabul.json` with 200+ Arabic-source persons. Sources: Ibn Khallikān, al-Dhahabī, Ibn al-Athīr. Use bilingual name fields (`latin_name`, `arabic_name`, `transliteration`).

---

## EPIC 4 — H-i-t-L UI Improvements

### MILESTONE 4.1 — Bulk Accept / Reject

**Problem:** Current UI requires one-click-per-decision for entity linking.

**Fix:** Add "Accept all top candidates" and "Reject all" buttons per document. Keyboard shortcuts: `a` = accept top, `x` = reject all, `n` = next document.

---

### MILESTONE 4.2 — Document Filter & Search

Add sidebar filters:
- By language (Latin / Old French / Arabic / Greek)
- By doc_type (chronicle / charter / narrative / letter)
- By extraction date (last 7d / 30d / all)
- By unresolved person count (0 / 1-5 / 6+)

---

### MILESTONE 4.3 — Extraction Confidence Overlay

Show a heat map in the text view: highlight person mentions by extraction confidence (green = high, yellow = medium, red = low). Helps identify where the model is uncertain.

---

### MILESTONE 4.4 — Relationship Graph Preview

In the person detail panel, show a mini-graph of relationships before saving:

```html
<div id="relationship-graph" data-person-id="AUTH:CR1"></div>
<script type="module" src="/js/graph-preview.js"></script>
```

Use D3.js force-directed layout. Clicking a node navigates to that person.

---

## EPIC 5 — CI/CD & Deployment

### MILESTONE 5.1 — Run Pipeline via SSH Deploy Key (not GitHub Actions secrets)

**Problem:** `GOOGLE_API_KEY` and `MISTRAL_API_KEY` live in GitHub Actions secrets. Rotation is cumbersome.

**Fix:** Move to a `secrets.yaml` file encrypted with `git-crypt` or SOPS:

```bash
# .github/workflows/pipeline.yml — replace secrets injection with:
- name: Pull secrets
  env:
    SOPS_AGE_KEY: ${{ secrets.SOPS_AGE_KEY }}
  run: |
    pip install sops
    sops --decrypt secrets.yaml.enc > secrets.yaml
    # secrets.yaml contains: GOOGLE_API_KEY, MISTRAL_API_KEY
```

---

### MILESTONE 5.2 — Per-Branch Preview Deployments

**Fix:** Extend `.github/workflows/pages.yml` to deploy PR previews:

```yaml
on:
  pull_request:
    branches: [main]

jobs:
  preview:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build site
        run: pip install -r requirements.txt && python scripts/run_pipeline.py
      - name: Deploy preview
        uses: nwtgck/actions-netlify@v3
        with:
          publish_dir: ./site
          productionBranch: main
          productionDeploy: false  # it's a preview
        env:
          NETLIFY_AUTH_TOKEN: ${{ secrets.NETLIFY_AUTH_TOKEN }}
```

**Acceptance:** Every PR gets a `https://pr-{n}--outremer-preview.netlify.app` URL.

---

### MILESTONE 5.3 — nightly Run with Result Notification

```yaml
schedule:
  - cron: "0 3 * * *"   # 03:00 UTC nightly

jobs:
  run:
    ...
  notify:
    needs: run
    if: always()
    steps:
      - name: Notify failure
        if: needs.run.result == 'failure'
        run: |
          curl -X POST https://api.github.com/repos/thodel/outremer/issues \
            -H "Authorization: token ${{ secrets.GH_TOKEN }}" \
            -d '{"title": "Nightly pipeline failed", "body": "Check Actions log"}'
```

---

## MILESTONE 5.4 — Local Dev Container

**File:** `Dockerfile` + `docker-compose.yml`

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y tesseract-ocr poppler-utils
RUN pip install easyocr  # GPU image separately
COPY requirements.txt .
RUN pip install -r requirements.txt
WORKDIR /repo
CMD ["python", "scripts/run_pipeline.py"]
```

Developers: `docker compose up` → pipeline runs locally, no API keys needed.

---

## Epic Summary

| Epic | Milestones | Priority | Effort |
|------|-----------|----------|--------|
| **1. LLM Abstraction** | 1.1 Config layer → 1.5 Smoke test | ⚠️ HIGH | Medium |
| **2. Pipeline Reliability** | 2.1 JSON recovery → 2.4 Run reports | ⚠️ HIGH | Low |
| **3. KG Enrichment** | 3.1 Wikidata links → 3.4 Arabic sources | MEDIUM | Medium |
| **4. H-i-t-L UI** | 4.1 Bulk actions → 4.4 Graph preview | MEDIUM | Medium |
| **5. CI/CD** | 5.1 SOPS secrets → 5.4 Dev container | LOW | Low |

---

## Recommended First Steps (Next 2 Weeks)

1. **Day 1–2:** Create `scripts/config.py` + `scripts/llm_client.py` (Epic 1, M1.1–M1.2)
2. **Day 3–4:** Port extraction to Ollama + Qwen3, verify output quality (Epic 1, M1.4)
3. **Day 5:** Add JSON recovery + retry logic (Epic 2, M2.1 + M2.3)
4. **Day 6–7:** Add Wikidata fuzzy matching to `build_unified_kg.py` (Epic 3, M3.1)
5. **Day 8+:** EasyOCR fallback for OCR (Epic 1, M1.3), then UI improvements (Epic 4)

---

## Open Questions for Tobias

1. Which local model provider do you want to target first — **Ollama** (easiest setup), **LM Studio** (better UI), or **vLLM** (higher throughput)?
2. Do you have a GPU available for EasyOCR or vLLM, or is this CPU-only?
3. Should the Arabic/Levantine authority expansion be a priority, or focus on completeness of existing Western crusader data first?
4. Should the GitHub Pages H-i-t-L UI be moved to a separate repo or stay in `site/`?
5. What is the target environment — your local machine, a lab server, or cloud VMs?