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
