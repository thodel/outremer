# OUTREMER — GPUStack Adaptation Plan

**Author:** DH bot (via OpenClaw)  
**Date:** 2026-07-05  
**Status:** Draft  
**Scope:** `github.com/thodel/outremer` only — no other projects, no MCP servers.

---

## Executive Summary

Replace the two proprietary API dependencies in the pipeline:

| Current | Replacement | Endpoint |
|---------|-------------|----------|
| `google-genai` (Gemini 2.0-flash) | GPUStack Qwen3 model | `https://tei.dh.unibe.ch/v1` |
| `mistralai` (Mistral OCR) | GPUStack MiniMax-M2.7 or EasyOCR | same endpoint or local |

**Key constraint:** All LLM calls run on `tei.dh.unibe.ch` — no external calls to Google, Mistral, or any other third-party LLM provider.

**Implementation model:** Mirror the pattern already proven in `thodel/agentic_historian`:
- `scripts/config.py` — env-var config for GPUStack
- `scripts/llm_client.py` — thin wrapper around `openai.OpenAI` with GPUStack base URL
- Rewire the two existing LLM call-sites (`extract_persons_google.py`, `run_pipeline.py`)

**What does NOT change:**
- `wikidata_reconcile.py` — uses Wikidata SPARQL API (not an LLM call), no changes needed
- `build_unified_kg.py` — offline KG builder, no LLM calls
- All scrapers — no LLM calls

---

## Epic 1 — GPUStack Integration ⚠️ HIGH PRIORITY

### MILESTONE 1.1 — Config Layer

**Files:** `scripts/config.py` (new), `.env.gpustack` (new, git-ignored), `.gitignore` (update)

Create `scripts/config.py`:

```python
# scripts/config.py
"""GPUStack configuration for the OUTREMER pipeline."""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

def _get(key: str, default=None):
    return os.environ.get(key, default)

# ── GPUStack ────────────────────────────────────────────────────────────────
GPUSTACK_BASE_URL    = _get("GPUSTACK_BASE_URL",  "https://tei.dh.unibe.ch/v1")
GPUSTACK_API_KEY     = _get("GPUSTACK_API_KEY",   "")
GPUSTACK_TIMEOUT     = int(_get("GPUSTACK_TIMEOUT", "120"))

# Model names (must match names registered in GPUStack)
EXTRACTION_MODEL     = _get("EXTRACTION_MODEL",   "qwen3-30b-a3b-instruct")
ORCHESTRATOR_MODEL   = _get("ORCHESTRATOR_MODEL", "minimax-m2.7")

# ── OCR ─────────────────────────────────────────────────────────────────────
# "gpustack" → use GPUStack MiniMax-M2.7 for OCR
# "easyocr"  → local EasyOCR (no API call, CPU/GPU)
OCR_ENGINE           = _get("OCR_ENGINE",         "easyocr")
```

Create `.env.gpustack` (git-ignored automatically since `.env*` is in `.gitignore`):

```env
# GPUStack (all LLM calls — tei.dh.unibe.ch)
GPUSTACK_BASE_URL=https://tei.dh.unibe.ch/v1
GPUSTACK_API_KEY=your-token-here

# Model names (check GPUStack dashboard for exact names)
EXTRACTION_MODEL=qwen3-30b-a3b-instruct
ORCHESTRATOR_MODEL=minimax-m2.7

# OCR engine: easyocr (local, no API) or gpustack (MiniMax-M2.7)
OCR_ENGINE=easyocr
```

Add to `.gitignore`:
```
.env.gpustack
```

**Acceptance:** Pipeline reads GPUStack config from `.env.gpustack` with no code changes.

---

### MILESTONE 1.2 — GPUStack Client (`llm_client.py`)

**File:** `scripts/llm_client.py` (new)

Mirrors the pattern from `thodel/agentic_historian/utils/gpustack_client.py`.

```python
# scripts/llm_client.py
"""Thin GPUStack client — wraps openai.OpenAI with GPUStack base URL."""
from __future__ import annotations

import logging
from typing import Any

import openai

from config import GPUSTACK_BASE_URL, GPUSTACK_API_KEY, GPUSTACK_TIMEOUT

logger = logging.getLogger(__name__)

# Reusable client (singleton per process)
_client: openai.OpenAI | None = None

def get_client() -> openai.OpenAI:
    """Return a shared OpenAI client pointed at GPUSTACK_BASE_URL."""
    global _client
    if _client is None:
        _client = openai.OpenAI(
            base_url=GPUSTACK_BASE_URL,
            api_key=GPUSTACK_API_KEY or "dummy",   # GPUStack may not require a key
            timeout=GPUSTACK_TIMEOUT,
        )
    return _client

def generate(prompt: str, *, system: str | None = None,
             model: str | None = None, **kwargs: Any) -> str:
    """
    Send a chat completion to GPUStack.

    Args:
        prompt     — user message
        system     — optional system prompt
        model      — override EXTRACTION_MODEL (None = use config default)
        **kwargs  — passed through to the API (temperature, max_tokens, …)

    Returns:
        The raw ``content`` string from the first assistant message.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    client = get_client()
    resp = client.chat.completions.create(
        model=model or EXTRACTION_MODEL,
        messages=messages,
        **kwargs,
    )
    return resp.choices[0].message.content or ""
```

**Acceptance:** `python -c "from scripts.llm_client import generate; print(generate('Say hello in one word'))"` → a response from `tei.dh.unibe.ch`.

---

### MILESTONE 1.3 — Port Person Extraction to GPUStack

**File:** `scripts/extract_persons_google.py` — replace `google.genai` calls

**Step 1:** Update the imports and client init (keep `use_genai_metadata` param name for compat):

```python
# Near line 871 — replace genai block
# BEFORE:
from google import genai
client = genai.Client(api_key=api_key)
resp = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=[prompt],
    config=genai.types.GenerateContentConfig(thinking_config=...)
)

# AFTER:
from scripts.llm_client import generate
raw = generate(
    prompt,
    system=SYSTEM_PROMPT,
    model=EXTRACTION_MODEL,
    max_tokens=_max_tokens,
    temperature=0.1,
)
```

**Step 2:** Adjust prompt for GPUStack models (ASCII delimiters, no emoji):

```python
# Replace emoji in SYSTEM_PROMPT section:
#   🚫 → [EXCLUDE]   ✅ → [INCLUDE]   📋 → [FORMAT]
# Remove Gemini-specific framing: "Respond with EXACTLY this JSON"
# Add instead: "Output valid JSON only. No markdown fences."
```

**Step 3:** Update `requirements.txt`:
- Remove: `google-genai`
- Add: `openai` (already implied by `mistralai` dep, but make explicit)

**Step 4:** In `run_pipeline.py` — remove `GOOGLE_API_KEY` from env-check messages.

**Acceptance:** `python scripts/run_pipeline.py --input-dir data/raw --genai-metadata` extracts persons using GPUStack (qwen3) with <10% quality delta vs Gemini baseline on benchmark documents.

---

### MILESTONE 1.4 — Port Mistral OCR to GPUStack + EasyOCR

**File:** `scripts/run_pipeline.py` — replace `_mistral_ocr()` with GPUStack MiniMax-M2.7 or EasyOCR

```python
def _ocr_image(path: Path) -> str:
    """
    OCR for image-only PDFs.
   优先级: EasyOCR (local, no API) > GPUStack MiniMax-M2.7 > Mistral > fallback
    """
    engine = os.environ.get("OCR_ENGINE", "easyocr").lower()

    if engine == "easyocr":
        result = _easyocr(path)
        if result:
            return result
        logger.warning("EasyOCR returned empty; falling back to GPUStack OCR")

    if engine in ("gpustack", "minimax"):
        result = _gpustack_ocr(path)
        if result:
            return result
        logger.warning("GPUStack OCR failed; falling back to Mistral")
        # fall through to mistral

    return _mistral_ocr(path)  # existing, keep as final fallback


def _gpustack_ocr(path: Path) -> str:
    """Use GPUStack MiniMax-M2.7 for document OCR."""
    import base64, json
    from scripts.llm_client import generate

    b64 = base64.b64encode(path.read_bytes()).decode()

    prompt = (
        "You are an OCR system. Given an image of a document page, transcribe ALL text "
        "exactly as it appears. Preserve line breaks, capitalization, and unusual characters. "
        "If the image is not a document page, say: [NOT_A_PAGE]\n\n"
        f"Image data: data:application/pdf;base64,{b64}"
    )
    try:
        text = generate(
            prompt,
            model=ORCHESTRATOR_MODEL,  # MiniMax-M2.7 for vision/OCR tasks
            max_tokens=8192,
            temperature=0.0,
        )
        if text == "[NOT_A_PAGE]":
            return ""
        return text.strip()
    except Exception as exc:
        logger.error("GPUStack OCR error: %s", exc)
        return ""


def _easyocr(path: Path) -> str:
    """Local EasyOCR on CPU/GPU — no API call, no API key needed."""
    try:
        import easyocr
    except ImportError:
        logger.debug("easyocr not installed")
        return ""

    # Cache the reader (init is expensive)
    if not hasattr(_easyocr, "_reader"):
        _easyocr._reader = easyocr.Reader(
            ["la", "en", "fr", "de", "it", "es"], gpu=True, verbose=False
        )

    results = _easyocr._reader.readtext(path.read_bytes())
    lines = [r[1] for r in results if r[2] > 0.25]
    return " ".join(lines).strip()
```

**Acceptance:** Switching `OCR_ENGINE=easyocr` produces comparable text on medieval Latin/Old French charters with no API call.

---

### MILESTONE 1.5 — Smoke Test

**File:** `scripts/test_llm_client.py` (new)

```python
#!/usr/bin/env python3
"""Smoke test for GPUStack integration."""
import sys, json
from scripts.llm_client import generate
from config import EXTRACTION_MODEL, ORCHESTRATOR_MODEL

def main():
    # Test extraction model
    print(f"Testing EXTRACTION_MODEL={EXTRACTION_MODEL}…")
    out = generate(
        "List 3 crusader kings of Jerusalem (Baldwin I–V) as JSON: "
        "[{\"name\": \"…\", \"title\": \"…\", \"years\": \"…\"}]",
        max_tokens=256,
    )
    print("Extraction model:", out[:200])

    # Test OCR instruction
    print(f"\nTesting ORCHESTRATOR_MODEL={ORCHESTRATOR_MODEL}…")
    out2 = generate(
        "Say 'OCR OK' if you can read this.", max_tokens=32
    )
    print("Orchestrator model:", out2)

    # Test JSON parsing
    try:
        data = json.loads(out)
        print(f"\n✅ JSON parsed: {len(data)} items")
    except json.JSONDecodeError as e:
        print(f"\n⚠️  JSON parse error: {e}")
        print("Raw output:", out)

if __name__ == "__main__":
    main()
```

Run: `python scripts/test_llm_client.py`

**Acceptance:** Both models respond, JSON parses correctly.

---

## Epic 2 — Pipeline Reliability ⚠️ HIGH PRIORITY

*(Does not require GPUStack access — offline improvements)*

### MILESTONE 2.1 — JSON Recovery

**File:** `scripts/extract_persons_google.py` — add `_parse_llm_json()`

```python
def _parse_llm_json(raw: str) -> dict | None:
    """Parse JSON from LLM output, handling markdown fences and extra text."""
    raw = raw.strip()
    # Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'```\s*$', '', raw, flags=re.MULTILINE)
    # Find first { ... last }
    start, end = raw.find('{'), raw.rfind('}') + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError:
            pass
    return None
```

Apply to: `extract_persons_and_metadata()` return value, `extract_persons()` return value.

---

### MILESTONE 2.2 — Chunk Boundary Respect

**File:** `scripts/extract_persons_google.py` — improve `_chunk_text()`

Split on `\n\n` (paragraph boundaries) not mid-sentence. Prevents splitting person mentions across chunks.

---

### MILESTONE 2.3 — Retry with Exponential Backoff

```python
import time, functools

def with_retry(fn, max_attempts=3, base_delay=2.0, logger=None):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        for attempt in range(max_attempts):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                if attempt == max_attempts - 1:
                    raise
                delay = base_delay * (2 ** attempt)
                if logger:
                    logger.warning("Retry %d/%d after %.1fs: %s", attempt+1, max_attempts, delay, exc)
                time.sleep(delay)
    return wrapper
```

Apply to: `generate()` call in `extract_persons_google.py`, `_gpustack_ocr()`, Wikidata SPARQL calls.

---

### MILESTONE 2.4 — Pipeline Run Reports

**File:** `scripts/run_pipeline.py` — write `data/staging/run_report.json` after each run:

```json
{
  "run_at": "2026-07-05T18:00:00Z",
  "docs_total": 12,
  "docs_ok": 10,
  "docs_failed": 2,
  "total_persons": 347,
  "llm_provider": "gpustack",
  "extraction_model": "qwen3-30b-a3b-instruct",
  "ocr_engine": "easyocr",
  "failures": [{"doc": "henri1_charter", "error": "timeout", "retry": 3}]
}
```

---

## Epic 3 — KG Enrichment & Authority Quality

*(No LLM changes — focuses on Wikidata linking and data quality)*

### MILESTONE 3.1 — Fuzzy Wikidata Matching (0 → 10k+ QID links)

**File:** `scripts/build_unified_kg.py` — replace exact match with RapidFuzz

```python
from rapidfuzz import fuzz

def match_wikidata_to_authority(auth_persons, wikidata_persons, threshold=85):
    for auth_id, person in auth_persons.items():
        name = person["preferred_label"]
        best_score, best_qid = 0, None
        for qid, wd in wikidata_persons.items():
            score = fuzz.token_sort_ratio(name, wd["preferred_label"])
            if score > best_score:
                best_score, best_qid = score, qid
        if best_score >= threshold:
            person["identifiers"]["wikidata_qid"] = best_qid
```

**Acceptance:** ≥50% of 126 authority persons get a `wikidata_qid`.

---

### MILESTONE 3.2 — Gender Field Fix

**File:** `scripts/build_unified_kg.py` — fix `load_wikidata_peerage()`

The P21 parsing already exists but populates `bio.gender` instead of `bio.sex`. Fix the field name. Verify 1,000 random Wikidata persons have gender populated.

---

## Epic Summary

| Epic | Milestones | Priority | GPUStack |
|------|-----------|----------|----------|
| **1. GPUStack Integration** | 1.1 Config → 1.5 Smoke test | ⚠️ HIGH | Yes |
| **2. Pipeline Reliability** | 2.1 JSON recovery → 2.4 Run reports | ⚠️ HIGH | No |
| **3. KG Enrichment** | 3.1 Fuzzy Wikidata matching → 3.2 Gender fix | MEDIUM | No |

---

## Recommended Implementation Order

```
Week 1
  Day 1  — M1.1: scripts/config.py + .env.gpustack + .gitignore
  Day 2  — M1.2: scripts/llm_client.py + smoke test
  Day 3  — M1.3: Port extract_persons_google.py to GPUStack (rm google-genai)
  Day 4  — M1.4: Port run_pipeline.py OCR to EasyOCR + GPUStack fallback
  Day 5  — M1.5: Run smoke test + verify extraction quality

Week 2
  Day 6  — M2.1: JSON recovery + chunk boundary fix
  Day 7  — M2.3: Retry decorator on all LLM calls
  Day 8  — M2.4: Run report JSON
  Day 9  — M3.1: Fuzzy Wikidata matching in build_unified_kg.py
  Day 10 — M3.2: Gender field fix + commit
```

---

## What Stays the Same

| File / Component | Reason |
|-----------------|--------|
| `wikidata_reconcile.py` | Uses Wikidata SPARQL API, not an LLM — no changes needed |
| `build_unified_kg.py` | Offline KG builder — no LLM, no API calls |
| All scrapers in `scrapers/` | No LLM calls |
| `scripts/process_staged.py` | Orchestration only — passes env vars through |
| `requirements.txt` core deps | RapidFuzz, pypdf stay; remove `google-genai` |

---

## Dependencies Removed

| Package | Where used | Replacement |
|---------|-----------|-------------|
| `google-genai` | `extract_persons_google.py` | `openai` + GPUStack |
| `mistralai` | `run_pipeline.py` | EasyOCR or GPUStack MiniMax |

Both can be removed from `requirements.txt` after migration is complete.

---

## Open Questions for Tobias

1. **GPUStack model names:** What are the exact model names registered in GPUStack for `tei.dh.unibe.ch`? I see `minimax-m2.7` and `qwen3-vl-30b-a3b-instruct` in `agentic_historian` config — are these the same names, or different registrations?
2. **OCR quality bar:** Is EasyOCR quality on medieval Latin charters acceptable, or is GPUStack MiniMax-M2.7 OCR preferred as primary path?
3. **Wikidata SPARQL:** Should `wikidata_reconcile.py` also use GPUStack for candidate scoring (instead of the current heuristic scorer)? That would be a later enhancement.
4. **API key:** Does GPUStack on `tei.dh.unibe.ch` require an API key, or is it open to the internal network?