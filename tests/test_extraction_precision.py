"""Tests for the heuristic-fallback precision work.

The fallback is not a nicety: GitHub Actions cannot reach GPUStack (every
chunk returns 403), so `_extract_gpustack` degrades per-chunk and the
fallback is what actually produces the published corpus. Measured on the
munro full-gold fixture it went from P 0.047 / R 0.318 / F1 0.082 to
P 0.553 / R 0.955 / F1 0.700.

Each test below pins one of the defects that caused that gap.
"""

import re

from extract_persons import (
    _PERSON_PATTERN,
    _extract_fallback,
    _is_bibliographic_noise,
    _is_modern_scholar,
    _is_person_like,
    _sanitise_text,
    _trim_person_span,
)


def _first(text: str) -> str:
    """First span the pipeline would actually keep (matched, trimmed, vetted)."""
    for m in _PERSON_PATTERN.finditer(text):
        span = _trim_person_span(m.group(0).strip())
        if span and _is_person_like(span):
            return span
    return ""


# ── pattern: joining and regnal numerals ─────────────────────────────────────

def test_consecutive_capitalised_tokens_join_into_one_name():
    # Previously "Thomas Fuller" matched as "Thomas" then "Fuller" — one false
    # positive plus one false negative for the same person.
    assert _first("the prejudice of the writer. Thomas Fuller is") == "Thomas Fuller"


def test_particle_joined_names_still_work():
    assert _first("According to Fulk of Chartres, Urban") == "Fulk of Chartres"


def test_regnal_numeral_is_captured():
    # Bare "Gregory" never matched gold "Gregory IX".
    assert _first("an energetic pontiff, Gregory IX., was elected") == "Gregory IX."


def test_regnal_capture_does_not_swallow_following_word():
    # A capital I starting the next word must not be read as a numeral.
    assert "In" not in _first("crusade of Louis In the year")


def test_hyphenated_compound_name_stays_whole():
    assert _first("readily with Richard the Lion-Hearted and") == "Richard the Lion-Hearted"


# ── span trimming ────────────────────────────────────────────────────────────

def test_leading_particle_phrase_is_discarded():
    # "of Clermont" is a prepositional phrase clipped out of "Council of
    # Clermont". The leading particle goes, and what remains is a place — so
    # nothing person-like survives.
    trimmed = _trim_person_span("of Clermont")
    assert trimmed == "" or not _is_person_like(trimmed)


def test_leading_particle_trimmed_when_a_real_name_follows():
    assert _trim_person_span("of Godfrey") == "Godfrey"


def test_leading_connective_is_trimmed_but_name_survives():
    assert _trim_person_span("Second Crusade Eugene III") == "Eugene III"


def test_toponym_attached_by_particle_is_kept():
    assert _trim_person_span("Godfrey of Bouillon") == "Godfrey of Bouillon"


def test_trailing_particle_removed():
    assert _trim_person_span("Bishops of") == "Bishops"


# ── person-likeness ──────────────────────────────────────────────────────────

def test_place_alone_is_not_a_person():
    assert not _is_person_like("Constantinople")
    assert not _is_person_like("Kingdom of Jerusalem")


def test_bare_title_is_not_a_person():
    assert not _is_person_like("Pope")
    assert not _is_person_like("Patriarch")


def test_deity_is_not_a_person():
    assert not _is_person_like("Allah")


def test_titled_person_is_a_person():
    assert _is_person_like("Pope Urban II")
    assert _is_person_like("Godfrey")


# ── the two context filters that deleted medieval subjects ───────────────────

def test_medieval_chronicler_cited_with_according_to_is_not_a_modern_scholar():
    # "According to X" is how a historian cites a MEDIEVAL chronicler; the old
    # pattern treated it as a modern-citation marker and deleted the person.
    ctx = "According to Fulk of   Chartres, Urban at Clermont used the"
    assert not _is_modern_scholar("Fulk of Chartres", ctx)


def test_prose_verb_states_does_not_mark_a_modern_scholar():
    ctx = "the marvelous effect of Bernard of Clairvaux's sermons and states that"
    assert not _is_modern_scholar("Bernard of Clairvaux", ctx)


def test_real_citation_apparatus_still_marks_a_modern_scholar():
    assert _is_modern_scholar("Riley-Smith", "Riley-Smith, cf. p. 12")
    assert _is_modern_scholar("Someone", "Someone (1983), pp. 44-51")


def test_scholar_surname_matches_whole_tokens_only():
    # "france" in the surname set previously matched a medieval "of France".
    assert not _is_modern_scholar("Robert of France", "")
    assert _is_modern_scholar("Smith", "")


def test_ordinary_prose_word_part_is_not_bibliographic_noise():
    ctx = "no one played a prominent   part, except Cardinal Pelagius, whose lack"
    assert not _is_bibliographic_noise("Cardinal Pelagius", ctx)


def test_narrative_context_does_not_flag_a_single_name():
    ctx = "after the capture of the city they elected Godfrey, Defender of the Holy"
    assert not _is_bibliographic_noise("Godfrey", ctx)


def test_genuine_bibliographic_context_still_filtered():
    assert _is_bibliographic_noise("Somebody", "Somebody, vol. 3, pp. 22, University Press")


# ── de-hyphenation ───────────────────────────────────────────────────────────

def test_line_break_hyphenation_is_rejoined():
    assert "Constantinople" in _sanitise_text("the city of Constanti-\nnople was")


def test_genuine_compound_hyphen_is_preserved():
    assert "Lion-Hearted" in _sanitise_text("Richard the Lion-Hearted rode")


# ── collectives ──────────────────────────────────────────────────────────────

def test_capitalised_collective_is_a_group_not_an_individual():
    # Persons were matched first, so "Crusaders" was claimed as an individual
    # and `seen_names` then blocked the collective pass entirely.
    res = _extract_fallback("The Crusaders marched. The Templars followed.")
    by_name = {p["name"].lower(): p for p in res["persons"]}
    assert by_name["crusaders"]["group"] is True
    assert by_name["crusaders"]["role"] == "collective"


def test_group_pattern_and_person_pattern_do_not_double_count():
    res = _extract_fallback("The Crusaders marched.")
    names = [p["name"].lower() for p in res["persons"]]
    assert names.count("crusaders") == 1


# ── end-to-end shape ─────────────────────────────────────────────────────────

def test_fallback_finds_titled_and_plain_names_in_a_passage():
    text = (
        "Pope Urban II preached at Clermont. According to Fulk of Chartres, "
        "Godfrey took the cross. Thomas Fuller later wrote of it."
    )
    names = {p["name"] for p in _extract_fallback(text)["persons"] if not p["group"]}
    assert "Pope Urban II" in names
    assert "Fulk of Chartres" in names
    assert "Thomas Fuller" in names
    # and the noise that used to dominate is gone
    assert "According" not in names
    assert not any(re.fullmatch(r"of \w+", n) for n in names)


# ── honest provenance when the model is unreachable ──────────────────────────

def test_all_chunks_failing_reports_heuristic_not_gpustack(monkeypatch):
    """CI cannot reach GPUStack (every chunk 403s). The document must not
    claim `gpustack` provenance when a regex produced every mention."""
    import extract_persons as E

    monkeypatch.setattr(E, "_extract_gpustack_chunk", _raise_403)
    monkeypatch.setenv("GPUSTACK_BASE_URL", "https://example.invalid/v1")
    res = E.extract_persons_and_metadata(
        "Pope Urban II preached at Clermont.", use_llm_metadata=False
    )
    eng = res["engine"]
    assert eng["provider"] == "heuristic"
    assert eng["configured_provider"] == "gpustack"
    assert eng["fallback_chunks"] == eng["chunks"] >= 1
    assert eng["degraded_reasons"]


def test_clean_run_still_reports_gpustack(monkeypatch):
    import extract_persons as E

    monkeypatch.setattr(
        E, "_extract_gpustack_chunk",
        lambda *a, **k: {"persons": [{"name": "Godfrey"}], "metadata": {}},
    )
    monkeypatch.setenv("GPUSTACK_BASE_URL", "https://example.invalid/v1")
    res = E.extract_persons_and_metadata("Godfrey took the cross.", use_llm_metadata=False)
    assert res["engine"]["provider"] == "gpustack"
    assert res["engine"]["fallback_chunks"] == 0


def _raise_403(*args, **kwargs):
    raise RuntimeError("403 Forbidden: Access denied")
