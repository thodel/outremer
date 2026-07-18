from extract_persons_google import _feedback_terms_for_prompt, _filter_and_reweight_persons


def _person(name, *, context="", confidence=0.8, group=False, title=None):
    return {
        "name": name,
        "raw_mention": name,
        "title": title,
        "epithet": None,
        "toponym": None,
        "role": None,
        "gender": "unknown",
        "group": group,
        "context": context,
        "confidence": confidence,
        "source_offset": 0,
    }


def test_blocked_allow_precedence():
    data = {
        "blocked_terms": ["See", "Kedar"],
        "allow_terms": ["see"],
        "auto_flagged": {},
    }
    terms = _feedback_terms_for_prompt(data)
    assert "See" not in terms
    assert "Kedar" in terms


def test_bibliographic_noise_is_hard_filtered():
    persons = [_person("Author", context="Journal of Medieval Studies, Vol. 1", confidence=0.95)]
    filtered, flagged = _filter_and_reweight_persons(persons, source_id="doc-a")
    assert filtered == []
    assert any(f["reason"] == "bibliographic_noise" for f in flagged)


def test_post_medieval_single_signal_penalizes_not_filters():
    persons = [_person("William", context="He was described in a later note dated 1654.", confidence=0.8)]
    filtered, flagged = _filter_and_reweight_persons(persons, source_id="doc-b")
    assert len(filtered) == 1
    assert filtered[0]["confidence"] < 0.8
    assert filtered[0]["confidence"] > 0.0
    assert any(f["reason"] == "post_medieval" for f in flagged) is False


def test_post_medieval_multiple_strong_signals_hard_filter():
    persons = [
        _person(
            "Professor Alice Brown",
            context="University archive entry, revised in 1999.",
            confidence=0.9,
        )
    ]
    filtered, flagged = _filter_and_reweight_persons(persons, source_id="doc-c")
    assert filtered == []
    assert any(f["reason"] == "post_medieval" for f in flagged)


# ── _record_problem_entities idempotency (nightly-churn fix) ────────────────

def _flag(name, *, reason="known_bad_entity", source="doc-a", context="ctx"):
    return {
        "name": name,
        "norm": name.lower(),
        "reason": reason,
        "source_id": source,
        "context": context,
    }


def test_record_problem_entities_idempotent_across_runs():
    from extract_persons_google import _record_problem_entities

    store = {"auto_flagged": {}}
    flagged = [_flag("According"), _flag("According")]
    _record_problem_entities(store, flagged)
    entry = store["auto_flagged"]["according"]
    assert entry["count"] == 2
    assert entry["reasons"] == {"known_bad_entity": 2}
    first_seen = entry["last_seen"]

    # Re-processing the same document must not inflate anything
    _record_problem_entities(store, flagged)
    entry = store["auto_flagged"]["according"]
    assert entry["count"] == 2
    assert entry["reasons"] == {"known_bad_entity": 2}
    assert entry["last_seen"] == first_seen


def test_record_problem_entities_sums_across_sources():
    from extract_persons_google import _record_problem_entities

    store = {"auto_flagged": {}}
    _record_problem_entities(store, [_flag("According", source="doc-a")])
    _record_problem_entities(store, [_flag("According", source="doc-b")])
    entry = store["auto_flagged"]["according"]
    assert entry["count"] == 2
    assert entry["sources"] == ["doc-a", "doc-b"]

    # A changed tally for one source replaces that source's contribution
    _record_problem_entities(
        store, [_flag("According", source="doc-a"), _flag("According", source="doc-a")]
    )
    entry = store["auto_flagged"]["according"]
    assert entry["count"] == 3
    assert entry["per_source"]["doc-a"]["count"] == 2


def test_record_problem_entities_migrates_legacy_inflated_entry():
    from extract_persons_google import _record_problem_entities

    store = {
        "auto_flagged": {
            "according": {
                "name": "According",
                "count": 270,  # inflated: one increment per nightly run
                "reasons": {"known_bad_entity": 267, "modern_scholar": 3},
                "sources": ["doc-a"],
                "last_seen": "2026-07-01T00:00:00+00:00",
                "last_context": "old",
            }
        }
    }
    _record_problem_entities(store, [_flag("According", source="doc-a")])
    entry = store["auto_flagged"]["according"]
    assert entry["count"] == 1
    assert entry["reasons"] == {"known_bad_entity": 1}
    assert entry["last_seen"] != "2026-07-01T00:00:00+00:00"
