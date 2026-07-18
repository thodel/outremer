# Linker operating point (M10.3)

Thresholds are config-backed (`scripts/config.py`, env-overridable):

| setting | value | meaning |
|---|---|---|
| `LINK_CANDIDATE_FLOOR` | 0.60 | minimum ensemble score to appear as a candidate |
| `LINK_MEDIUM` | 0.75 | status "medium" |
| `LINK_HIGH` | 0.90 | status "high" |

## Why the floor stays at 0.60

Sweep over the adjudicated fixtures (2026-07-12, `python -m evaluation.sweep`):

| floor | agreement | accept_hit | accept_miss | reject_hit | reject_avoided |
|---|---|---|---|---|---|
| 0.60 | **0.8545** | 4 | 5 | 3 | 43 |
| 0.65 | 0.8000 | 0 | 9 | 2 | 44 |
| 0.70 | 0.8182 | 0 | 9 | 1 | 45 |
| 0.75–0.85 | 0.8182 | 0 | 9 | 1 | 45 |

Raising the floor to 0.65 destroys **all** confirmed correct links while
avoiding only one more rejected pair. Every scholar-confirmed match scores
in [0.60, 0.65) — a symptom of the thin 126-person authority file, where
even correct matches are partial-name matches. Revisit after the authority
file is enriched.

## Known gold caveats (feeds #36)

**Resolved 2026-07-18 (#44):** two adjudicated "accepts" linked *different
persons who shared a first name* — "Count Robert of Flanders" → AUTH:CR16
(Thierry of Flanders) and "Ralph of Caen" → AUTH:CR24 (Ralph of Dury);
the authority file did not contain the mentioned persons at all. Both were
re-adjudicated to reject (comments in `data/decisions.json`), the missing
figures were added to the authority file with Wikidata QIDs (#45:
AUTH:CR184 Godfrey of Bouillon, AUTH:CR185 Robert II of Flanders,
AUTH:CR186 Ralph of Caen), and fixtures were regenerated. The linker's
declines now count as `reject_avoided`: authority agreement moved
0.8545 → 0.8909, combined 0.8873 → 0.9155.

## Matching upgrades in this operating point (M10.1 + M10.2)

- punctuation → space in `normalise` (hyphenated toponyms split)
- particle folding (`de/of/von/du/der/des/le/la/d`) as a second
  comparison — "Godefroy de Bouillon" ≡ "Godefroy of Bouillon" (was 0.85)
- damped `token_set_ratio` on folded, multi-token forms only — a naive
  raw-form ensemble measurably promoted wrong persons via shared
  given name + particle ("Ralph of Caen" → "Ralph II of Fougères" at 0.79)

Guarded by `tests/test_linker_matching.py`.
