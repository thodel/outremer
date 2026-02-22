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
Extract ALL person mentions from the text below — including individuals, collectives (ethnic groups, armies, unnamed people), and ambiguous references.

For each person/group return a JSON object with these exact fields:
  name          (string)   : normalised name or label (use the most common English form if known)
  raw_mention   (string)   : exact text span as it appears in the source
  title         (string|null) : e.g. "Count", "Bishop", "Sultan"
  epithet       (string|null) : e.g. "the Lion", "the Bold"
  toponym       (string|null) : place associated with the person, e.g. "Flanders"
  role          (string|null) : e.g. "pilgrim", "knight", "merchant", "refugee"
  gender        (string)   : "m", "f", or "unknown"
  group         (boolean)  : true if collective (army, ethnic group, unnamed crowd)
  context       (string)   : surrounding ~100 characters of text
  confidence    (number)   : 0.0–1.0, your certainty this is a real person/group mention

Also extract document metadata with these fields:
  title    (string|null)
  author   (string|null)
  year     (string|null)
  language (string|null) : ISO 639 code if detectable
  doc_type (string|null) : "chronicle", "charter", "narrative", "letter", "list", or "other"

Respond ONLY with valid JSON — no markdown fences, no commentary — matching this schema:
{{
  "persons": [...],
  "metadata": {{ "title": ..., "author": ..., "year": ..., "language": ..., "doc_type": ... }}
}}

TEXT:
"""


def _build_prompt(language_code: Optional[str] = None) -> str:
    hint = _LANGUAGE_HINTS.get(language_code or "", "")
    return _JSON_PROMPT_BASE.format(language_hint=f"\n{hint}" if hint else "")

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


def _dedup_persons(all_persons: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate persons across chunks by normalised name — keep highest confidence."""
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

def _extract_gemini_chunk(client: Any, chunk: str, language: Optional[str] = None) -> Dict[str, Any]:
    """Call Gemini on a single chunk. Returns raw dict or raises."""
    clean_chunk = _sanitise_text(chunk)
    prompt = _build_prompt(language) + clean_chunk
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


def _extract_gemini(text: str, use_genai_metadata: bool, language: Optional[str] = None) -> Dict[str, Any]:
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
            result = _extract_gemini_chunk(client, chunk, language=language)
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

    persons = _dedup_persons(all_persons)
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

    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if api_key:
        return _extract_gemini(text, use_genai_metadata, language=language)
    else:
        result = _extract_fallback(text)
        if use_genai_metadata:
            result["bibtex"] = _build_bibtex(result["metadata"])
        return result
