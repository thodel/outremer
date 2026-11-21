"""M16.2 (#80, Epic 16, #66): fuse recognition candidates into a
best-fit transcription.

The agreement gate runs first: if the pool's max pairwise CER is below
``FUSION_AGREEMENT_CER_THRESHOLD`` (default 0.05) the engines agree and
the most central candidate (smallest total pairwise distance, ties by
input order) is taken as-is — path ``consensus``, zero LLM calls.

Above the gate the strategy decides:

* ``vote`` (default): candidates are aligned token-wise against the
  most central one; a column is resolved only by strict majority, and
  each run of unresolved columns is arbitrated with one bounded LLM
  call — the prompt carries the span, its immediate context and each
  candidate's reading of it, never the whole page.
* ``llm_merge``: one LLM call merges the raw texts.

``path`` and ``arbitration_calls`` on the result record which path a
page took and what it cost. The LLM is an injected
``Callable[[str], str]`` (production binding: ``scripts.llm_client.generate``)
so the module runs offline. The transcription is rebuilt from
whitespace tokens: whitespace is collapsed and per-column surface forms
follow the first candidate that emitted the voted token.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass

from evaluation.metrics import candidate_distance
from scripts.config import FUSION_AGREEMENT_CER_THRESHOLD, FUSION_STRATEGY

FUSION_STRATEGIES = ("vote", "llm_merge")
PATH_CONSENSUS = "consensus"
PATH_VOTE = "vote"
PATH_LLM_MERGE = "llm_merge"

_CONTEXT_TOKENS = 10


@dataclass(frozen=True)
class FusionResult:
    """What a page came out of the fusion, and what it cost (audit record)."""

    transcription: str
    path: str
    strategy: str
    agreement: dict
    arbitration_calls: int
    unresolved_spans: int = 0


def _pair_distance(a: str, b: str) -> float:
    """Symmetric CER-like distance between two candidates (see metrics)."""
    return candidate_distance([a, b])["max_cer"]


def _most_central(texts: list[str]) -> int:
    """Index of the candidate with the smallest total pairwise distance."""
    best, best_score = 0, None
    for i, text in enumerate(texts):
        score = sum(
            _pair_distance(text, other)
            for j, other in enumerate(texts)
            if j != i
        )
        if best_score is None or score < best_score:
            best, best_score = i, score
    return best


def _entries_for_candidate(
    ref: list[str], cand: list[str]
) -> list[tuple[int, str]]:
    """Map candidate tokens onto reference positions via opcodes.

    Returns (position, token) pairs over 0..len(ref)-1; extra candidate
    tokens (insertions) attach to the nearest preceding position.
    """
    entries: list[tuple[int, str]] = []
    matcher = difflib.SequenceMatcher(a=ref, b=cand, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            entries.extend((i1 + k, cand[j1 + k]) for k in range(i2 - i1))
        elif tag == "replace":
            k = 0
            for p in range(i1, i2):
                if k < j2 - j1:
                    entries.append((p, cand[j1 + k]))
                    k += 1
            for extra in cand[j1 + k : j2]:
                entries.append((max(i2 - 1, 0), extra))
        elif tag == "insert":
            anchor = max(i1 - 1, 0)
            entries.extend((anchor, token) for token in cand[j1:j2])
        # "delete": the candidate has a gap here — nothing to emit.
    return entries


def _build_grid(
    texts: list[str], ref_index: int
) -> tuple[list[list[tuple[int, str, str]]], list[str]]:
    """Align all candidates on the reference candidate's token positions.

    Returns the column grid — one column per reference token, each a
    list of (candidate index, surface token, casefolded token) with the
    reference's own entry first — plus the reference's surface tokens.
    """
    ref_surface = texts[ref_index].split()
    ref = [t.casefold() for t in ref_surface]
    per_candidate: list[dict[int, list[str]]] = [{} for _ in texts]
    for i, text in enumerate(texts):
        if i == ref_index:
            continue
        cand = [t.casefold() for t in text.split()]
        for pos, token in _entries_for_candidate(ref, cand):
            per_candidate[i].setdefault(pos, []).append(token)
    grid: list[list[tuple[int, str, str]]] = []
    for p, surface in enumerate(ref_surface):
        column: list[tuple[int, str, str]] = [(ref_index, surface, surface.casefold())]
        for i in range(len(texts)):
            if i == ref_index:
                continue
            for token in per_candidate[i].get(p, []):
                column.append((i, token, token))
        grid.append(column)
    return grid, ref_surface


def _vote_column(column: list[tuple[int, str, str]]) -> str | None:
    """The casefolded token holding a strict majority, or None."""
    counts: dict[str, int] = {}
    for _, _, folded in column:
        counts[folded] = counts.get(folded, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(top) == 1:
        return top[0][0]
    if top[0][1] > top[1][1] and top[0][1] * 2 > len(column):
        return top[0][0]
    return None


def _span_prompt(
    span: list[int],
    grid: list[list[tuple[int, str, str]]],
    engines: list[str],
) -> str:
    before = " ".join(
        column[0][1] for column in grid[span[0] - _CONTEXT_TOKENS : span[0]]
    )
    after = " ".join(
        column[0][1]
        for column in grid[span[-1] + 1 : span[-1] + 1 + _CONTEXT_TOKENS]
    )
    lines = [
        "These transcriptions come from different OCR engines reading the same "
        "page and disagree in one span.",
        "Return ONLY the best reading of the span, with no explanation.",
        "",
        f"Preceding context: {before or '—'}",
        f"Following context: {after or '—'}",
        "",
        "Candidate readings of the span:",
    ]
    for i in range(len(engines)):
        fragment = " ".join(
            entry[1] for p in span for entry in grid[p] if entry[0] == i
        )
        if not fragment:
            continue
        lines.append(f"  {engines[i]}: {fragment}")
    return "\n".join(lines)


def _merge_prompt(engines: list[str], texts: list[str]) -> str:
    lines = [
        "The following transcriptions come from different OCR engines reading "
        "the same page.",
        "Merge them into one best-fitting transcription.",
        "Return ONLY the transcription, with no explanation.",
        "",
        "Engine readings:",
    ]
    for engine, text in zip(engines, texts):
        lines.append(f"  {engine}:\n{text}")
    return "\n".join(lines)


def _fallback_fragment(
    span: list[list[tuple[int, str, str]]], n_candidates: int, ref_index: int
) -> str:
    """Deterministic fallback when the arbitrator returns nothing: the
    reference candidate's reading of the span, else the longest reading."""
    fragments = []
    for i in range(n_candidates):
        fragments.append(
            " ".join(
                entry[1] for column in span for entry in column if entry[0] == i
            )
        )
    if fragments[ref_index]:
        return fragments[ref_index]
    return max(fragments, key=len) if any(fragments) else ""


def fuse(
    candidates: dict[str, str],
    *,
    strategy: str | None = None,
    agreement_threshold: float | None = None,
    llm: Callable[[str], str] | None = None,
) -> FusionResult:
    """Fuse per-engine candidates of one page into a transcription.

    ``candidates`` maps engine name to raw text, in input order. Above
    the gate, ``strategy`` (default ``FUSION_STRATEGY``) chooses
    ``vote`` or ``llm_merge``. Raises ``ValueError`` for an unknown
    strategy, or when the vote path has unresolved spans but no ``llm``.
    """
    if not candidates:
        raise ValueError("at least one candidate is required")
    strategy = strategy or FUSION_STRATEGY
    if strategy not in FUSION_STRATEGIES:
        raise ValueError(
            f"unknown fusion strategy {strategy!r}; expected one of {FUSION_STRATEGIES}"
        )
    threshold = (
        FUSION_AGREEMENT_CER_THRESHOLD if agreement_threshold is None else agreement_threshold
    )

    engines = list(candidates)
    texts = list(candidates.values())
    agreement = candidate_distance(texts)

    if agreement["max_cer"] < threshold:
        ref_index = _most_central(texts)
        return FusionResult(
            transcription=texts[ref_index],
            path=PATH_CONSENSUS,
            strategy=strategy,
            agreement=agreement,
            arbitration_calls=0,
        )

    if strategy == PATH_LLM_MERGE:
        if llm is None:
            raise ValueError("llm_merge above the agreement gate requires an llm")
        merged = llm(_merge_prompt(engines, texts)).strip()
        if not merged:
            raise ValueError("the arbitrator returned no transcription")
        return FusionResult(
            transcription=merged,
            path=PATH_LLM_MERGE,
            strategy=strategy,
            agreement=agreement,
            arbitration_calls=1,
        )

    ref_index = _most_central(texts)
    grid, _ = _build_grid(texts, ref_index)
    spans: list[list[int]] = []
    resolved: list[str | None] = []
    current: list[int] = []
    for p, column in enumerate(grid):
        winner = _vote_column(column)
        if winner is None:
            current.append(p)
            resolved.append(None)
        else:
            if current:
                spans.append(current)
                current = []
            surface = next(
                entry[1] for entry in column if entry[2] == winner
            )
            resolved.append(surface)
    if current:
        spans.append(current)

    calls = 0
    for span in spans:
        if llm is None:
            raise ValueError(
                f"the vote path has {len(spans)} unresolved span(s) but no "
                "llm was given; arbitration above the gate is mandatory"
            )
        calls += 1
        verdict = llm(_span_prompt(span, grid, engines)).strip()
        if not verdict:
            verdict = _fallback_fragment([grid[p] for p in span], len(texts), ref_index)
        resolved[span[0]] = verdict

    return FusionResult(
        transcription=" ".join(part for part in resolved if part),
        path=PATH_VOTE,
        strategy=strategy,
        agreement=agreement,
        arbitration_calls=calls,
        unresolved_spans=len(spans),
    )
