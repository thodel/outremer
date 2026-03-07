"""
extract_persons_google.py
─────────────────────────
Person + metadata extraction for the Outremer pipeline.

Primary path  : Google Gemini (gemini-2.0-flash) — requires GOOGLE_API_KEY env var.
Fallback path : regex / heuristic NER — runs without any API key.

Public API
──────────
    extract_persons_and_metadata(text, *, use_genai_metadata=True) -> Dict[str, Any]

Returns
───────
{
  "persons": [
    {
      "name":          str,
      "raw_mention":   str,        # exact text span
      "title":         str | None, # "Count", "Bishop", …
      "epithet":       str | None, # "the Lion"
      "toponym":       str | None, # "Flanders"
      "role":          str | None, # "pilgrim", "knight", …
      "gender":        str | None, # "m" / "f" / "unknown"
      "group":         bool,       # True if collective
      "context":       str,        # ~100-char surrounding snippet
      "confidence":    float,      # 0.0–1.0
      "source_offset": int | None
    }
  ],
  "metadata": {
    "title":    str | None,
    "author":   str | None,
    "year":     str | None,
    "language": str | None,
    "doc_type": str | None  # "chronicle"/"charter"/"narrative"/"other"
  },
  "bibtex": str
}
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

_GEMINI_MODEL = "gemini-2.0-flash"
_CHUNK_SIZE = 5_500   # smaller = shorter Gemini response = less truncation
_CHUNK_OVERLAP = 800

_LANGUAGE_HINTS: Dict[str, str] = {
    "la": """\
LANGUAGE NOTE: This is a Latin medieval text. Key patterns to recognise:
- Titles/offices: rex, regina, comes, episcopus, archiepiscopus, patriarcha, dux, princeps, imperator, papa, miles, dominus, frater, magister, abbas, prior, constabularius, senescallus
- Naming: Latin genitive constructions (e.g. "Godefridus de Bullonio"), toponymic epithets (de + place), filial (filius/filia + parent)
- Collectives: milites, peregrini, Franci, Saraceni, Graeci, Armeni, pagani, fideles, crucesignati
- Uncertainty: treat "quidam", "nescio quis" as unnamed/uncertain individuals
""",
    "fro": """\
LANGUAGE NOTE: This is an Old French (Anglo-Norman or continental) medieval text. Key patterns:
- Titles: rei, conte, duc, prince, evesque, arcevesque, mestre, seigneur, dame, chevalier, connestable
- Naming: de + toponym for family/origin, le/la + epithet (e.g. "le Lion", "la Blanche")
- Collectives: pelerins, croisez, Francs, Sarrazins, Grecs, Armeniens
""",
    "ar": """\
LANGUAGE NOTE: This is an Arabic medieval text. Key patterns:
- Name chains: ism (given name), nasab (ibn/bint + father), nisba (al- + place/tribe), laqab (honorific title)
- Titles: sultan, malik (king), amir (emir/prince), khalifa (caliph), qadi (judge), shaykh, wazir, atabeg
- Collectives: Franj (Franks/Crusaders), Muslimun, Rum (Byzantine Greeks), Arman (Armenians)
- Note: transliterated Arabic names may appear in multiple variant spellings
""",
    "el": """\
LANGUAGE NOTE: This is a Byzantine Greek medieval text. Key patterns:
- Titles: basileus/basilissa (emperor/empress), megas doux, sebastokrator, kaisar, despotes, strategos, doux, protokuropalates
- Names often Hellenised versions of Latin or Frankish originals
- Collectives: Latinoi (Latins/Crusaders), Persai (Turks), Armenioi
""",
    "de": """\
LANGUAGE NOTE: This is a Middle High German medieval text. Key patterns:
- Titles: König, Königin, Graf, Bischof, Erzbischof, Fürst, Herzog, Ritter, Herr, Meister
- Naming: von + place name; Beiname (epithet) often follows given name
- Collectives: Pilger, Kreuzfahrer, Franken, Sarazenen, Griechen
""",
}

_JSON_PROMPT_BASE = """\
You are a historical NLP assistant specialising in the medieval Levant (Crusades era, 11th–14th centuries).
{language_hint}
{feedback_hint}
Extract ALL person mentions from the text below — individuals, collectives (armies, ethnic groups, unnamed crowds), and ambiguous references.

═══════════════════════════════════════════════════════════
🚫 ABSOLUTE EXCLUSION RULES — NEVER EXTRACT THESE 🚫
═══════════════════════════════════════════════════════════

DO NOT EXTRACT — these are NEVER persons (confidence = 0.0):

❌ BIBLIOGRAPHIC / PUBLISHER INFO:
   "Vol", "Volume", "No", "Number", "pp", "Pages", "p.", "pp."
   "Published", "Publication", "Copyright", "All rights reserved"
   "ISBN", "DOI", "ISSN", "JSTOR", "Stable URL", "Accessed"
   "University Press", "Oxford", "Cambridge", "Press", "Publisher"
   "Journal", "Review", "Proceedings", "Transactions", "Bulletin"
   "Series", "Volume", "Issue", "Edition", "Reprint"

❌ DOCUMENT STRUCTURE MARKERS:
   "Author", "Editor", "Translator", "Introduction", "Chapter"
   "Section", "Part", "Book", "Article", "Abstract", "Keywords"
   "Bibliography", "References", "Notes", "Appendix", "Index"
   "Source", "Title", "Language", "Date", "Type"

❌ CITATION MARKERS:
   "see", "cf", "ibid", "op. cit.", "loc. cit.", "passim"
   "ed.", "eds.", "trans.", "tr.", "rev.", "repr."
   "n.", "nn.", "fn", "footnote"

❌ MODERN SCHOLARS (confidence ≤ 0.10, role = "modern scholar"):
   Academic names appearing in citations, footnotes, or bibliography
   Examples: "Riley-Smith", "Mayer", "Tyerman", "Asbridge", "France"
   "Cahen", "Runciman", "Grousset", "Kedar", "Prawer", "Hamilton"
   If followed by "argues", "writes", "notes", "cf", "see" → modern scholar

❌ SINGLE COMMON NOUNS (confidence = 0.0):
   "Source", "Title", "Language", "Type", "Date", "Author"
   "Editor", "Review", "Press", "Vol", "Published", "Copyright"

═══════════════════════════════════════════════════════════
✅ WHAT TO EXTRACT — MEDIEVAL PERSONS ONLY ✅
═══════════════════════════════════════════════════════════

EXTRACT with HIGH confidence (0.7–1.0):

✓ Named individuals with medieval titles:
  "King Baldwin", "Count Raymond of Tripoli", "Sultan Saladin"
  "Pope Urban II", "Patriarch William", "Bishop Odo"
  "Duke Godfrey", "Prince Bohemond", "Emperor Alexios"

✓ Named individuals without titles (if context is medieval narrative):
  "Tancred", "Fulcher of Chartres", "Ibn al-Qalanisi"

✓ Collective groups (group = true):
  "the Franks", "the Crusaders", "the Saracens", "pilgrims"
  "the garrison", "the army", "knights", "Templars"
  "Muslims", "Christians", "Greeks", "Armenians"

✓ Unnamed but specific individuals:
  "a certain knight", "one of the princes", "a Turkish emir"
  (set name = descriptive phrase, confidence = 0.4–0.6)

═══════════════════════════════════════════════════════════
📋 OUTPUT FORMAT — STRICT JSON ONLY 📋
═══════════════════════════════════════════════════════════

Respond with EXACTLY this JSON structure — NO markdown, NO commentary:

{{
  "persons": [
    {{
      "name": "Full name WITH title (e.g., 'Count Raymond')",
      "raw_mention": "Exact text span from source",
      "title": "Title only (e.g., 'Count') or null",
      "epithet": "Epithet if present (e.g., 'the Lion') or null",
      "toponym": "Place name if present (e.g., 'Tripoli') or null",
      "role": "Role (e.g., 'crusader', 'knight') or null",
      "gender": "m | f | unknown",
      "group": true/false,
      "context": "~100 chars of surrounding text",
      "confidence": 0.0–1.0
    }}
  ],
  "metadata": {{
    "title": "Document title or null",
    "author": "Author name or null",
    "year": "Year (4 digits) or null",
    "language": "ISO 639 code (e.g., 'la', 'en', 'fro')",
    "doc_type": "chronicle | charter | narrative | letter | list | modern_study | other"
  }}
}}

CONFIDENCE GUIDELINES:
  0.8–1.0 : Clear medieval person with title/name in narrative context
  0.5–0.7 : Likely medieval person, some uncertainty
  0.3–0.4 : Uncertain — possibly medieval, possibly noise
  0.1–0.2 : Modern scholar/author mentioned in citation
  0.0     : Bibliographic metadata, document structure, common nouns

BEFORE YOU OUTPUT, ASK:
  "Would this person appear in a medieval chronicle or charter?"
  If NO → confidence = 0.0, do not extract.

═══════════════════════════════════════════════════════════
TEXT TO ANALYZE:
═══════════════════════════════════════════════════════════

"""


def _sanitise_feedback_term(term: str) -> str:
    t = str(term or "").strip()
    t = re.sub(r"[\x00-\x1f\x7f]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace('"', "'")
    return t[:120]


def _build_feedback_hint(terms: List[str]) -> str:
    if not terms:
        return ""
    clean_terms: List[str] = []
    for term in terms:
        cleaned = _sanitise_feedback_term(term)
        if cleaned and cleaned not in clean_terms:
            clean_terms.append(cleaned)
    if not clean_terms:
        return ""
    lines = "\n".join(f'   - "{t}"' for t in clean_terms[:40])
    return (
        "PROJECT-SPECIFIC BAD ENTITY MEMORY (from previous extractions):\n"
        "Treat these as known false positives. Do not return them as persons.\n"
        f"{lines}\n"
    )


def _build_prompt(language_code: Optional[str] = None, blocked_terms: Optional[List[str]] = None) -> str:
    hint = _LANGUAGE_HINTS.get(language_code or "", "")
    feedback_hint = _build_feedback_hint(blocked_terms or [])
    return _JSON_PROMPT_BASE.format(
        language_hint=f"\n{hint}" if hint else "",
        feedback_hint=f"\n{feedback_hint}" if feedback_hint else "",
    )

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _normalise(s: str) -> str:
    """Lowercase + strip accents + collapse whitespace."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).lower().strip()


def _citekey(title: str, year: Optional[str]) -> str:
    slug = re.sub(r"[^a-z0-9]", "", _normalise(title))[:20]
    yr = year or "0000"
    h = hashlib.md5(title.encode()).hexdigest()[:4]
    return f"{slug}{yr}{h}"


def _build_bibtex(metadata: Dict[str, Any]) -> str:
    """Build a BibTeX entry from metadata dict. Returns '' if too sparse."""
    t = metadata.get("title") or ""
    a = metadata.get("author") or ""
    y = metadata.get("year") or ""
    if not t:
        return ""
    dtype = metadata.get("doc_type") or "other"
    btype = "book" if dtype in ("book",) else "article"
    key = _citekey(t, y)
    lines = [f"@{btype}{{{key},"]
    if a:
        lines.append(f"  author = {{{a}}},")
    lines.append(f"  title  = {{{t}}},")
    if y:
        lines.append(f"  year   = {{{y}}},")
    lang = metadata.get("language")
    if lang:
        lines.append(f"  note   = {{Language: {lang}}},")
    lines.append("}")
    return "\n".join(lines)


def _sanitise_text(text: str) -> str:
    """Strip control characters that break JSON when embedded in Gemini responses."""
    # Keep: tab (\x09), newline (\x0a), carriage return (\x0d), and all printable
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_feedback_store() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "blocked_terms": [],
        "allow_terms": [],
        "auto_flagged": {},
    }


def _load_entity_feedback(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return _default_feedback_store()
    p = Path(path)
    if not p.exists():
        return _default_feedback_store()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Invalid feedback store at %s; resetting.", p)
        return _default_feedback_store()
    if not isinstance(raw, dict):
        return _default_feedback_store()
    out = _default_feedback_store()
    out["blocked_terms"] = [str(x).strip() for x in (raw.get("blocked_terms") or []) if str(x).strip()]
    out["allow_terms"] = [str(x).strip() for x in (raw.get("allow_terms") or []) if str(x).strip()]
    auto = raw.get("auto_flagged") or {}
    out["auto_flagged"] = auto if isinstance(auto, dict) else {}
    return out


def _save_entity_feedback(path: Optional[str], data: Dict[str, Any]) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _feedback_terms_for_prompt(data: Dict[str, Any], min_auto_count: int = 2) -> List[str]:
    terms: List[str] = []
    allow_norms = {_normalise(str(x)) for x in (data.get("allow_terms") or []) if str(x).strip()}
    for x in data.get("blocked_terms") or []:
        label = str(x).strip()
        if label and _normalise(label) not in allow_norms:
            terms.append(label)

    auto = data.get("auto_flagged") or {}
    if isinstance(auto, dict):
        ranked: List[Tuple[int, str]] = []
        for _, entry in auto.items():
            if not isinstance(entry, dict):
                continue
            count = int(entry.get("count") or 0)
            label = str(entry.get("name") or "").strip()
            if count >= min_auto_count and label and _normalise(label) not in allow_norms:
                ranked.append((count, label))
        for _, label in sorted(ranked, reverse=True):
            if label not in terms:
                terms.append(label)
    return terms[:120]


def _record_problem_entities(
    feedback_store: Dict[str, Any],
    flagged: List[Dict[str, str]],
) -> None:
    auto = feedback_store.setdefault("auto_flagged", {})
    if not isinstance(auto, dict):
        return
    ts = _utc_now_iso()
    for item in flagged:
        norm = item.get("norm")
        if not norm:
            continue
        entry = auto.get(norm)
        if not isinstance(entry, dict):
            entry = {
                "name": item.get("name") or norm,
                "count": 0,
                "reasons": {},
                "sources": [],
                "last_seen": ts,
                "last_context": "",
            }
            auto[norm] = entry

        entry["name"] = item.get("name") or entry.get("name") or norm
        entry["count"] = int(entry.get("count") or 0) + 1
        reasons = entry.setdefault("reasons", {})
        reason = item.get("reason") or "unknown"
        reasons[reason] = int(reasons.get(reason) or 0) + 1
        src = item.get("source_id")
        if src:
            sources = entry.setdefault("sources", [])
            if src not in sources:
                sources.append(src)
                entry["sources"] = sources[-20:]
        entry["last_seen"] = ts
        if item.get("context"):
            entry["last_context"] = item["context"][:300]


def _repair_json(raw: str) -> str:
    """Best-effort repair of common Gemini JSON issues before parsing."""
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    # Strip control characters from the response itself
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", raw)
    return raw


def _recover_truncated_json(raw: str) -> Dict[str, Any]:
    """
    Attempt to salvage persons from a truncated Gemini JSON response.
    Finds the last complete person object (ending in '}') inside the persons array
    and reconstructs a valid minimal JSON document from it.
    """
    # Try to extract whatever complete person objects we can
    persons: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}

    # Find the persons array start
    persons_start = raw.find('"persons"')
    if persons_start == -1:
        return {"persons": persons, "metadata": metadata}

    bracket_start = raw.find("[", persons_start)
    if bracket_start == -1:
        return {"persons": persons, "metadata": metadata}

    # Walk through looking for complete {...} objects
    # Use a simple bracket counter to find each complete object
    i = bracket_start + 1
    depth = 0
    obj_start = -1

    while i < len(raw):
        c = raw[i]
        if c == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and obj_start != -1:
                obj_str = raw[obj_start:i + 1]
                try:
                    obj = json.loads(obj_str)
                    coerced = _coerce_person(obj)
                    if coerced:
                        persons.append(coerced)
                except (json.JSONDecodeError, Exception):
                    pass
                obj_start = -1
        elif c == "]" and depth == 0:
            break  # end of persons array (possibly truncated)
        i += 1

    # Try to extract metadata if it appears after "metadata"
    meta_start = raw.find('"metadata"')
    if meta_start != -1:
        brace_start = raw.find("{", meta_start)
        if brace_start != -1:
            depth = 0
            for j in range(brace_start, len(raw)):
                if raw[j] == "{":
                    depth += 1
                elif raw[j] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            metadata = json.loads(raw[brace_start:j + 1])
                        except Exception:
                            pass
                        break

    return {"persons": persons, "metadata": metadata}


def _chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> List[Tuple[int, str]]:
    """Split text into overlapping chunks. Returns list of (offset, chunk)."""
    if len(text) <= size:
        return [(0, text)]
    chunks: List[Tuple[int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append((start, text[start:end]))
        if end == len(text):
            break
        start += size - overlap
    return chunks


# Bibliographic noise patterns — catch false positives that slip through
_BIB_NOISE_PATTERNS = re.compile(
    r"\b(vol(ume)?|no\.?|number|pp\.?|pages?|published|publication|copyright|"
    r"isbn|doi|issn|jstor|url|accessed|retrieved|available|press|publisher|"
    r"journal|review|proceedings|transactions|bulletin|series|edition|"
    r"author|editor|translator|introduction|chapter|section|part|book|"
    r"article|abstract|keywords|bibliography|references|notes|appendix|"
    r"index|source|title|language|date|type|all rights reserved)\b",
    re.I
)

_MODERN_SCHOLAR_PATTERNS = re.compile(
    r"\b(argues|writes|notes|observes|suggests|claims|states|according to|"
    r"cf\.?|see|ibid|op\. cit\.|loc\. cit\.|passim|ed\.|eds\.|trans\.|tr\.|rev\.|repr\.)\b",
    re.I
)


def _is_bibliographic_noise(name: str, context: str = "") -> bool:
    """Check if a name is likely bibliographic metadata."""
    name_lower = name.lower().strip()
    
    # Single-word common nouns that are never persons
    if name_lower in {"source", "title", "language", "type", "date", "author",
                      "editor", "review", "press", "vol", "published", "copyright",
                      "volume", "number", "pages", "pp", "no", "isbn", "doi"}:
        return True
    
    # Publisher/journal patterns
    if any(x in name_lower for x in ["university press", "oxford university",
                                      "cambridge university", "journal of",
                                      "proceedings of", "review of"]):
        return True
    
    if _BIB_NOISE_PATTERNS.search(name):
        return True

    # Context-only rule: apply narrowly to short, untitled spans.
    # This avoids dropping real names that appear near bibliographic words.
    if context and len(name.split()) <= 2:
        title_like = re.search(
            r"\b(king|queen|count|duke|prince|emperor|pope|bishop|patriarch|sultan|emir|lord|lady)\b",
            name,
            re.I,
        )
        if not title_like and _BIB_NOISE_PATTERNS.search(context):
            return True

    return False


def _is_modern_scholar(name: str, context: str = "") -> bool:
    """Check if a name is likely a modern scholar (not medieval person)."""
    # Common crusades scholar names
    scholar_surnames = {"riley", "smith", "mayer", "tyerman", "asbridge", "france",
                        "cahen", "runciman", "grousset", "kedar", "prawer", "hamilton",
                        "edgington", "jotischky", "barber", "boas", "folda", "rodenberg"}
    
    name_lower = name.lower()
    if any(surname in name_lower for surname in scholar_surnames):
        return True
    
    # Check context for citation markers
    if _MODERN_SCHOLAR_PATTERNS.search(context):
        return True
    
    return False


def _is_post_medieval_name(name: str, context: str = "") -> bool:
    """Check if a name is likely post-medieval (after 1500)."""
    name_lower = name.lower()
    
    # Modern titles/honorifics
    modern_titles = {"professor", "prof.", "dr.", "mr.", "mrs.", "ms.", "ph.d.", "m.d.",
                     "ceo", "president", "minister", "ambassador", "senator", "governor"}
    if any(t in name_lower for t in modern_titles):
        return True
    
    # Modern institutional affiliations
    modern_inst = {"university", "institute", "foundation", "museum", "archive",
                   "library", "department", "faculty", "research center"}
    if any(i in name_lower for i in modern_inst):
        return True
    
    # Check context for modern date references
    modern_dates = re.findall(r'\b(1[5-9]\d{2}|20\d{2})\b', context)
    if modern_dates:
        # If only modern dates (1500+) appear, likely post-medieval
        if all(int(d) > 1500 for d in modern_dates):
            return True
    
    return False


def _problem_reason(
    person: Dict[str, Any],
    blocked_norms: set,
) -> Optional[str]:
    name = str(person.get("name") or "").strip()
    context = str(person.get("context") or "")
    group = bool(person.get("group"))
    if not name:
        return "empty_name"

    name_norm = _normalise(name)
    if name_norm in blocked_norms:
        return "known_bad_entity"
    if _is_bibliographic_noise(name, context):
        return "bibliographic_noise"
    if _is_post_medieval_name(name, context) and not group:
        return "post_medieval"
    if len(name.split()) > 8:
        return "name_too_long"
    if re.search(r"\d", name):
        return "contains_digits"
    if not group and len(name.split()) == 1 and len(name) <= 2:
        return "token_too_short"
    if not group and re.fullmatch(r"[a-z][a-z\s'\-]+", name):
        return "lowercase_non_name"
    # Scholars frequently appear in citation context and pollute medieval set.
    if _is_modern_scholar(name, context) and not person.get("title") and not group:
        return "modern_scholar"
    return None


def _filter_and_reweight_persons(
    persons: List[Dict[str, Any]],
    *,
    blocked_terms: Optional[List[str]] = None,
    source_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Filter noisy entities and emit machine-readable diagnostics."""
    filtered: List[Dict[str, Any]] = []
    flagged: List[Dict[str, str]] = []
    blocked_norms = {_normalise(x) for x in (blocked_terms or []) if x}

    for p in persons:
        name = p.get("name", "")
        context = p.get("context", "")
        reason = _problem_reason(p, blocked_norms)
        if reason:
            flagged.append(
                {
                    "name": str(name),
                    "norm": _normalise(str(name)),
                    "reason": reason,
                    "source_id": source_id or "",
                    "context": str(context)[:220],
                }
            )
            logger.debug("Filtered problematic entity '%s' (%s)", name, reason)
            continue

        confidence = p.get("confidence", 0.5)
        if len(str(name).split()) == 1 and not p.get("title") and confidence < 0.5:
            name_lower = str(name).lower()
            if name_lower in {"the", "and", "but", "for", "with", "from", "into"}:
                flagged.append(
                    {
                        "name": str(name),
                        "norm": _normalise(str(name)),
                        "reason": "common_word",
                        "source_id": source_id or "",
                        "context": str(context)[:220],
                    }
                )
                continue
        filtered.append(p)

    return filtered, flagged


def _dedup_persons(all_persons: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate persons across chunks by normalised name and keep best confidence."""
    seen: Dict[str, Dict[str, Any]] = {}
    for p in all_persons:
        key = _normalise(p.get("name") or p.get("raw_mention") or "")
        if not key:
            continue
        if key not in seen or p.get("confidence", 0) > seen[key].get("confidence", 0):
            seen[key] = p
    return list(seen.values())


def _safe_float(v: Any, default: float = 0.5) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _coerce_person(raw: Any) -> Optional[Dict[str, Any]]:
    """Coerce a raw dict from Gemini into the expected person schema."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name") or raw.get("raw_mention") or ""
    if not name:
        return None
    return {
        "name": str(name).strip(),
        "raw_mention": str(raw.get("raw_mention") or name).strip(),
        "title": raw.get("title") or None,
        "epithet": raw.get("epithet") or None,
        "toponym": raw.get("toponym") or None,
        "role": raw.get("role") or None,
        "gender": raw.get("gender") or "unknown",
        "group": bool(raw.get("group", False)),
        "context": str(raw.get("context") or "")[:200],
        "confidence": _safe_float(raw.get("confidence"), 0.5),
        "source_offset": raw.get("source_offset") or None,
    }


def _coerce_metadata(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        "title": raw.get("title") or None,
        "author": raw.get("author") or None,
        "year": raw.get("year") or None,
        "language": raw.get("language") or None,
        "doc_type": raw.get("doc_type") or None,
    }


# ──────────────────────────────────────────────
# Fallback: heuristic NER (no API key needed)
# ──────────────────────────────────────────────

# Patterns for medieval person-like tokens
_TITLE_WORDS = re.compile(
    r"\b(King|Queen|Count|Countess|Duke|Duchess|Prince|Princess|Emperor|"
    r"Empress|Pope|Bishop|Archbishop|Patriarch|Sultan|Emir|Caliph|Amir|"
    r"Sir|Lord|Lady|Master|Brother|Fra|Don|Sire|Baron|Viscount|"
    r"Constable|Marshal|Seneschal|Castellan|Abbot|Abbess)\b",
    re.I,
)

_PERSON_PATTERN = re.compile(
    r"(?:"
    r"(?:(?:King|Queen|Count|Countess|Duke|Duchess|Prince|Princess|Emperor|"
    r"Empress|Pope|Bishop|Archbishop|Sultan|Emir|Amir|Sir|Lord|Lady|Master|"
    r"Brother|Fra|Don|Sire|Baron|Viscount|Constable|Marshal|Seneschal|Abbot|Abbess)\s+)?"
    r"(?:[A-Z][a-zéèêëàâùûüîïôçœæÀ-ÿ]+(?:\s+(?:de|of|von|van|le|la|the|du|d'|al-|ibn|bin|bar)\s+)?"
    r"(?:[A-Z][a-zéèêëàâùûüîïôçœæÀ-ÿ\-]+)?)"
    r")"
)

_GROUP_PATTERN = re.compile(
    r"\b(pilgrims?|crusaders?|knights?|Templars?|Hospitallers?|Franks?|"
    r"Saracens?|Muslims?|Christians?|Jews?|Greeks?|Armenians?|Syrians?|"
    r"refugees?|merchants?|artisans?|women|children|clergy|soldiers?|"
    r"captives?|settlers?|colonists?)\b",
    re.I,
)


def _extract_fallback(text: str) -> Dict[str, Any]:
    """Heuristic extraction when no API key is available."""
    persons: List[Dict[str, Any]] = []
    seen_names: set = set()

    # Individual persons
    for m in _PERSON_PATTERN.finditer(text):
        span = m.group(0).strip()
        if len(span) < 3 or len(span.split()) > 6:
            continue
        norm = _normalise(span)
        if norm in seen_names:
            continue
        # Skip if it's just a common word
        if norm in {"the", "and", "but", "for", "nor", "yet"}:
            continue
        seen_names.add(norm)
        start = max(0, m.start() - 50)
        end = min(len(text), m.end() + 50)
        title_m = _TITLE_WORDS.match(span)
        persons.append({
            "name": span,
            "raw_mention": span,
            "title": title_m.group(0) if title_m else None,
            "epithet": None,
            "toponym": None,
            "role": None,
            "gender": "unknown",
            "group": False,
            "context": text[start:end].replace("\n", " "),
            "confidence": 0.30,
            "source_offset": m.start(),
        })

    # Collectives
    for m in _GROUP_PATTERN.finditer(text):
        span = m.group(0).strip()
        norm = _normalise(span)
        if norm in seen_names:
            continue
        seen_names.add(norm)
        start = max(0, m.start() - 50)
        end = min(len(text), m.end() + 50)
        persons.append({
            "name": span,
            "raw_mention": span,
            "title": None,
            "epithet": None,
            "toponym": None,
            "role": "collective",
            "gender": "unknown",
            "group": True,
            "context": text[start:end].replace("\n", " "),
            "confidence": 0.25,
            "source_offset": m.start(),
        })

    # Metadata: try to guess from first 500 chars
    header = text[:500]
    year_m = re.search(r"\b(1[0-9]{3})\b", header)
    metadata: Dict[str, Any] = {
        "title": None,
        "author": None,
        "year": year_m.group(1) if year_m else None,
        "language": "en",
        "doc_type": "other",
    }
    # Very rough doc_type guess
    if re.search(r"\bcharter\b|\bdonation\b|\bgrant\b", text[:300], re.I):
        metadata["doc_type"] = "charter"
    elif re.search(r"\bchronicle\b|\bannals?\b", text[:300], re.I):
        metadata["doc_type"] = "chronicle"

    return {"persons": persons, "metadata": metadata, "bibtex": ""}


# ──────────────────────────────────────────────
# Gemini extraction
# ──────────────────────────────────────────────

def _extract_gemini_chunk(
    client: Any,
    chunk: str,
    language: Optional[str] = None,
    blocked_terms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Call Gemini on a single chunk. Returns raw dict or raises."""
    clean_chunk = _sanitise_text(chunk)
    prompt = _build_prompt(language, blocked_terms=blocked_terms) + clean_chunk
    response = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    raw_text = response.text or "{}"
    raw_text = _repair_json(raw_text)

    # First try clean parse
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Response was likely truncated — salvage whatever complete objects exist
    logger.debug("Attempting truncation recovery for chunk.")
    recovered = _recover_truncated_json(raw_text)
    if recovered.get("persons"):
        logger.info("Recovered %d person(s) from truncated response.", len(recovered["persons"]))
        return recovered

    # Nothing salvageable — let caller handle fallback
    raise ValueError(f"Unrecoverable JSON from Gemini (length={len(raw_text)})")


def _extract_gemini(
    text: str,
    use_genai_metadata: bool,
    language: Optional[str] = None,
    blocked_terms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Full Gemini extraction with chunking."""
    try:
        from google import genai  # type: ignore
    except ImportError:
        logger.warning("google-genai not installed; using fallback.")
        return _extract_fallback(text)

    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        logger.warning("GOOGLE_API_KEY not set; using fallback extraction.")
        return _extract_fallback(text)

    try:
        client = genai.Client(api_key=api_key)
    except Exception as exc:
        logger.error("Failed to init Gemini client: %s", exc)
        return _extract_fallback(text)

    chunks = _chunk_text(text)
    all_persons: List[Dict[str, Any]] = []
    merged_metadata: Dict[str, Any] = {}

    for offset, chunk in chunks:
        try:
            result = _extract_gemini_chunk(
                client,
                chunk,
                language=language,
                blocked_terms=blocked_terms,
            )
        except Exception as exc:
            logger.warning("Gemini chunk failed (offset=%d): %s", offset, exc)
            result = _extract_fallback(chunk)

        for p in result.get("persons") or []:
            coerced = _coerce_person(p)
            if coerced is None:
                continue
            # Adjust source offset by chunk offset
            if coerced["source_offset"] is not None:
                coerced["source_offset"] += offset
            all_persons.append(coerced)

        # Merge metadata from first chunk that has content
        if not merged_metadata.get("title") and result.get("metadata"):
            merged_metadata = _coerce_metadata(result["metadata"])

    persons = all_persons
    metadata = merged_metadata or _coerce_metadata({})

    bibtex = ""
    if use_genai_metadata:
        bibtex = _build_bibtex(metadata)

    return {"persons": persons, "metadata": metadata, "bibtex": bibtex}


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def extract_persons_and_metadata(
    text: str,
    *,
    use_genai_metadata: bool = True,
    language: Optional[str] = None,
    feedback_path: Optional[str] = None,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract person mentions and document metadata from *text*.

    Uses Google Gemini (gemini-2.0-flash) when GOOGLE_API_KEY is set;
    falls back to heuristic regex NER otherwise.

    Parameters
    ----------
    text : str
        Full text of the historical source document.
    use_genai_metadata : bool
        If True, also extract/generate document metadata and BibTeX.

    Returns
    -------
    dict with keys: "persons", "metadata", "bibtex"
    """
    if not text or not text.strip():
        return {"persons": [], "metadata": {}, "bibtex": ""}

    text = _sanitise_text(text)
    feedback_store = _load_entity_feedback(feedback_path)
    feedback_terms = _feedback_terms_for_prompt(feedback_store)

    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if api_key:
        result = _extract_gemini(
            text,
            use_genai_metadata,
            language=language,
            blocked_terms=feedback_terms,
        )
    else:
        result = _extract_fallback(text)
        if use_genai_metadata:
            result["bibtex"] = _build_bibtex(result["metadata"])

    filtered_persons, flagged = _filter_and_reweight_persons(
        result.get("persons") or [],
        blocked_terms=feedback_terms,
        source_id=source_id,
    )
    result["persons"] = _dedup_persons(filtered_persons)

    if feedback_path:
        if flagged:
            _record_problem_entities(feedback_store, flagged)
        _save_entity_feedback(feedback_path, feedback_store)

    result["quality"] = {
        "filtered_problem_entities": len(flagged),
        "feedback_store": feedback_path,
    }
    return result
