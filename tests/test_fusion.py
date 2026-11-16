"""M16.2 (#80) fusion — offline, with a stubbed LLM.

The stub records every prompt, so the tests can assert what bounded
arbitration means: one call per unresolved span, each seeing the span
plus a fixed context window, never the whole page.
"""

from evaluation import fusion
from evaluation.fusion import PATH_CONSENSUS, PATH_LLM_MERGE, PATH_VOTE

# 30 distinct tokens, page-shaped; the disagreement tests span positions 5..8.
WORDS = [
    "deus", "verbum", "principium", "lux", "tenebrae",
    "vita", "homo", "filius", "pater", "spiritus",
    "gratia", "fides", "amor", "lex", "iudicium",
    "regnum", "angelus", "sanctus", "peccatum", "redemptionem",
    "gloria", "aeternitas", "creatio", "mundum", "homines",
    "gregem", "pastorem", "ovem", "portam", "via",
]
REF = " ".join(WORDS)


class _RecordingLLM:
    def __init__(self, answer: str):
        self.answer = answer
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


def _boom(prompt: str) -> str:  # any LLM call is a test failure
    raise AssertionError(f"the LLM must not be called; prompt: {prompt!r}")


def _spans_replaced(text: str, start: int, end: int, replacement: str) -> str:
    tokens = text.split()
    tokens[start:end] = replacement.split()
    return " ".join(tokens)


def test_agreeing_pool_takes_consensus_without_llm():
    # 123-token page pool: two candidates each differ in one token.
    words = (WORDS * 5)[:123]
    ref = " ".join(words)
    result = fusion.fuse(
        {"vlm": ref,
         "kraken-catmus_medieval": _spans_replaced(ref, 20, 21, "gloriose"),
         "trocr-essoins-middle-latin": _spans_replaced(ref, 55, 56, "gregis")},
        llm=_boom,
    )
    # "Done when": agreeing pages cost zero arbitration calls.
    assert result.path == PATH_CONSENSUS
    assert result.arbitration_calls == 0
    assert result.agreement["max_cer"] < 0.05
    # Most central candidate (the one with no differences) is taken as-is.
    assert result.transcription == ref


def test_gate_runs_before_strategy():
    words = (WORDS * 5)[:123]
    ref = " ".join(words)
    result = fusion.fuse(
        {"vlm": ref, "kraken": _spans_replaced(ref, 20, 21, "gloriose")},
        strategy=PATH_LLM_MERGE,
        llm=_boom,
    )
    # An agreeing page takes the consensus even under llm_merge.
    assert result.path == PATH_CONSENSUS
    assert result.arbitration_calls == 0
    assert result.strategy == PATH_LLM_MERGE


def test_single_candidate_is_consensus():
    result = fusion.fuse({"vlm": REF}, llm=None)
    assert result.path == PATH_CONSENSUS
    assert result.transcription == REF


def test_vote_path_arbitrates_one_bounded_call_per_span():
    b = _spans_replaced(REF, 5, 9, "guilhem pontieu comite domno")
    c = _spans_replaced(REF, 5, 9, "guillems ponti comitis domini")
    llm = _RecordingLLM("guilhem de pontieu")
    result = fusion.fuse({"vlm": REF, "kraken": b, "trocr": c}, llm=llm)
    assert result.path == PATH_VOTE
    assert result.arbitration_calls == 1
    assert result.unresolved_spans == 1
    # Above the gate (character-based CER of the most divergent pair).
    assert result.agreement["max_cer"] > 0.05
    expected = _spans_replaced(REF, 5, 9, "guilhem de pontieu")
    assert result.transcription == expected
    # Bounded: the single call sees all three readings of the span, each
    # engine named — but not the tail of the page.
    assert len(llm.prompts) == 1
    prompt = llm.prompts[0]
    assert "guilhem pontieu comite domno" in prompt
    assert "guillems ponti comitis domini" in prompt
    assert "vita homo filius pater" in prompt  # the vlm's reading of the span
    assert "vlm" in prompt and "kraken" in prompt and "trocr" in prompt
    # Context window: the 10th token after the span is in, the rest is not.
    assert "peccatum" in prompt  # index 18, last context token
    for token in ("redemptionem", "aeternitas", "portam", "via"):
        assert token not in prompt, f"the arbitration prompt must stay span-bounded: {token}"


def test_vote_path_majority_needs_no_arbitration():
    # kraken and trocr share a four-token deviation: 2/3 majority in the
    # differing columns — above the gate, zero unresolved spans, no LLM.
    b = _spans_replaced(REF, 20, 24, "dominus salvatorem reges gentes")
    result = fusion.fuse({"vlm": REF, "kraken": b, "trocr": b}, llm=None)
    assert result.agreement["max_cer"] > 0.05
    assert result.path == PATH_VOTE
    assert result.arbitration_calls == 0
    assert result.unresolved_spans == 0
    assert result.transcription == b


def test_llm_merge_makes_exactly_one_call():
    b = _spans_replaced(REF, 5, 9, "guilhem pontieu comite domno")
    c = _spans_replaced(REF, 5, 9, "guillems ponti comitis domini")
    llm = _RecordingLLM("one merged transcription")
    result = fusion.fuse(
        {"vlm": REF, "kraken": b, "trocr": c}, strategy=PATH_LLM_MERGE, llm=llm
    )
    assert result.path == PATH_LLM_MERGE
    assert result.arbitration_calls == 1
    assert result.transcription == "one merged transcription"
    assert len(llm.prompts) == 1
    for text in (REF, b, c):
        assert text in llm.prompts[0]


def test_gate_boundaries_are_strictly_below():
    # Max pairwise CER exactly at the threshold is *above* the gate: the
    # issue defines agreement as "below this".
    llm = _RecordingLLM("c")
    result = fusion.fuse(
        {"a": "a a b", "b": "a a c"},
        agreement_threshold=0.2,  # 1/5 char distance = 0.2 exactly
        llm=llm,
    )
    assert result.path == PATH_VOTE
    assert result.transcription == "a a c"
    # And 1/20 = 0.05 exactly is not below the default 0.05 either.
    a = " ".join(["a"] * 9 + ["bb"])
    b = " ".join(["a"] * 9 + ["bc"])
    result = fusion.fuse({"a": a, "b": b}, llm=_RecordingLLM("bb"))
    assert result.path == PATH_VOTE
    assert result.transcription == a


def test_vote_without_llm_raises_on_unresolved_span():
    b = _spans_replaced(REF, 5, 9, "guilhem pontieu comite domno")
    try:
        fusion.fuse({"vlm": REF, "kraken": b}, llm=None)
    except ValueError as e:
        assert "no llm" in str(e)
    else:
        raise AssertionError("unresolved spans without an llm must raise")


def test_empty_arbitration_falls_back_to_reference_reading():
    b = _spans_replaced(REF, 5, 9, "guilhem pontieu comite domno")
    llm = _RecordingLLM("   ")
    result = fusion.fuse({"vlm": REF, "kraken": b}, llm=llm)
    assert result.path == PATH_VOTE
    assert result.arbitration_calls == 1
    # The reference candidate's reading of the span stands in.
    assert result.transcription == REF


def test_unknown_strategy_and_empty_pool_raise():
    try:
        fusion.fuse({"vlm": REF}, strategy="majority")
    except ValueError as e:
        assert "unknown fusion strategy" in str(e)
    else:
        raise AssertionError("unknown strategy must raise")
    try:
        fusion.fuse({})
    except ValueError as e:
        assert "at least one candidate" in str(e)
    else:
        raise AssertionError("an empty candidate pool must raise")
