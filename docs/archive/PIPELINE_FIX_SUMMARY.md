# Outremer Pipeline Fix Summary

**Date:** 2026-02-24  
**Issue:** NER extraction producing excessive bibliographic noise (585 persons → ~150 real)  
**Root cause:** Gemini API failure → fallback to regex extraction with no semantic understanding

---

## The Problem

### Before Fix
- **Riley-Smith article**: 585 extracted "persons"
  - Examples of noise: `"Proceedings of"`, `"Philosophical"`, `"Vol"`, `"Published"`, `"Oxford University"`
  - Real medieval persons buried in noise: `"Pope Urban II"`, `"Raymond of Toulouse"`, `"Bohemond"`
- **Extraction mode**: `fallback` (Gemini API failed, used regex)
- **Confidence scores**: All ≤ 0.3 (no high-confidence extractions)
- **Authority linking**: 0% success (no `kg_id` matches written)

### Why It Happened
1. **Gemini API timeout or rate limit** during original pipeline run
2. **Fallback regex extractor** has no semantic understanding
3. **No post-processing filter** to remove bibliographic metadata
4. **Prompt didn't explicitly forbid** extracting journal metadata

---

## The Solution (4 Steps)

### ✅ Step 1: Fixed Gemini Extraction Prompt
**File:** `scripts/extract_persons_google.py`

**Changes:**
- Added explicit blacklist of bibliographic terms (Section 3 of prompt)
- Added contextual validation rules (Section 7)
- Clear examples of what NOT to extract
- Confidence = 0.0 for bibliographic noise

**Key additions to prompt:**
```
⚠️ DO NOT EXTRACT BIBLIOGRAPHIC METADATA ⚠️
NEVER extract these as persons:
- Journal names: "Proceedings of", "Philosophical Society"
- Publisher info: "University Press", "Oxford University"
- Volume/issue: "Vol", "Number", "pp"
- Identifiers: "ISBN", "DOI", "JSTOR"
```

### ✅ Step 2: Post-Processing Noise Filter
**File:** `scripts/filter_ner_noise.py`

**Features:**
- Blacklist of 60+ bibliographic terms
- Regex patterns for volume/page numbers, years
- Whitelist of medieval naming patterns (regnal numbers, toponyms, titles)
- Modern scholar detection from context clues
- Configurable strict mode

**Results on Riley-Smith:**
- Before: 585 persons, 585 links
- After: 451 persons, 194 links
- Removed: 134 unique noise entities (23% reduction)
- Links reduced more (67%) because noisy links discarded

### ✅ Step 3: Unified Knowledge Graph Builder
**File:** `scripts/build_unified_kg.py`

**Integrates three sources:**
1. **Outremer Authority** (126 curated persons from Omeka XML)
2. **Wikidata Peerage pre-1500** (~23,689 persons with birth/death < 1500)
3. **Extracted persons** (pipeline NER output)

**Matching strategy:**
- Tier 1: Exact normalized match (confidence ≥ 0.9)
- Tier 2: Fuzzy + contextual (confidence 0.6–0.9)
- Tier 3: Weak candidates (confidence < 0.6, needs review)

**Output:** `data/unified_kg.json`
- Single canonical record per person
- Cross-references: AUTH:CR1 ↔ Q1000874 ↔ extracted mentions
- Provenance tracking for every assertion
- Curation flags for human review

### ✅ Step 4: Pipeline Re-runner
**File:** `scripts/rerun_pipeline_fixed.py`

**Orchestrates all fixes:**
```bash
# Re-extract with fixed prompt + filter + build KG
python scripts/rerun_pipeline_fixed.py --raw-dir data/raw/ --build-kg

# Or just filter existing extractions
python scripts/rerun_pipeline_fixed.py --filter-only

# Strict mode (require medieval patterns)
python scripts/rerun_pipeline_fixed.py --filter-only --strict
```

---

## Data Model

See `docs/INTEGRATED_DATA_MODEL.md` for full schema.

**Unified Person Record:**
```json
{
  "id": "OUTREMER:person:0001",
  "preferred_label": "Baldwin IV of Jerusalem",
  "identifiers": {
    "outremer_auth": "AUTH:CR1",
    "wikidata_qid": "Q1000874"
  },
  "names": {
    "preferred": "Baldwin IV of Jerusalem",
    "variants": ["Baldwin the Leper", "Baudouin IV"],
    "normalized": ["baldwin iv jerusalem", "baldwin leper"]
  },
  "bio": {
    "birth": {"date": "1161"},
    "death": {"date": "1185"},
    "gender": "m"
  },
  "provenance": {
    "sources": [
      {"type": "authority", "confidence": 1.0},
      {"type": "wikidata", "match_type": "exact"}
    ]
  }
}
```

---

## Next Actions

### Immediate (Tobias)
1. **Re-run pipeline** on raw PDFs with fixed prompt:
   ```bash
   cd /home/th/repos/outremer
   python scripts/rerun_pipeline_fixed.py --raw-dir data/raw/ --build-kg
   ```

2. **Review filtered results** in `site/data/filtered/`

3. **Check unified KG** in `data/unified_kg.json`

### Short-term (Development)
1. **Run Wikidata reconciliation** on remaining `no_match` persons
2. **Update explorer.html** to show unified KG instead of separate sources
3. **Add bulk curation UI** (accept/reject multiple matches at once)
4. **Implement phonetic matching** (Soundex/Metaphone) for name variants

### Medium-term
1. **Add more knowledge sources**: VIAF, GND, Zotero authors
2. **Export to TEI-XML** with standardized `<persName>` references
3. **Train custom NER model** on curated Outremer data
4. **API endpoint** for querying unified KG

---

## Files Changed/Created

| File | Status | Purpose |
|------|--------|---------|
| `scripts/extract_persons_google.py` | ✏️ Modified | Fixed prompt with blacklist |
| `scripts/filter_ner_noise.py` | ➕ New | Post-processing noise filter |
| `scripts/build_unified_kg.py` | ➕ New | Unified KG builder |
| `scripts/rerun_pipeline_fixed.py` | ➕ New | Pipeline orchestrator |
| `docs/INTEGRATED_DATA_MODEL.md` | ➕ New | Schema documentation |
| `docs/PIPELINE_FIX_SUMMARY.md` | ➕ New | This file |

---

## Testing

### Test the filter:
```bash
python scripts/filter_ner_noise.py \
  --input site/data/rileysmith-motivesearliestcrusaders-1983-92cc17aaccd3.json \
  --output site/data/filtered-test.json
```

### Test the KG builder:
```bash
python scripts/build_unified_kg.py
# Output: data/unified_kg.json
```

### Full pipeline test:
```bash
python scripts/rerun_pipeline_fixed.py \
  --raw-dir data/raw/ \
  --build-kg \
  --strict
```

---

## Success Metrics

- **Precision**: >90% of extracted persons are real (currently ~25%)
- **Recall**: >80% of real persons in text are captured
- **Authority linking**: >50% of extracted persons linked to AUTH or QID
- **Noise reduction**: <10% bibliographic false positives

Current baseline (Riley-Smith fallback extraction):
- Precision: ~25% (149 real / 585 total)
- Authority linking: 0%
- Noise: ~60% bibliographic metadata

Expected after fix:
- Precision: >90% (with Gemini + filtering)
- Authority linking: >50% (with unified KG)
- Noise: <5%
