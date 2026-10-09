# Linker operating point (M10.3)

Thresholds are config-backed (`scripts/config.py`, env-overridable):

| setting | value | meaning |
|---|---|---|
| `LINK_CANDIDATE_FLOOR` | 0.65 | minimum ensemble score to appear as a candidate |
| `LINK_MEDIUM` | 0.75 | status "medium" |
| `LINK_HIGH` | 0.90 | status "high" |

## Why the floor is 0.65 (since 2026-10-09, M19.0 / M19.3)

Re-sweep over the fixtures regenerated from the **repaired** gold
(`python -m evaluation.authority_enrichment_report`, recorded in
`evaluation/baselines/epic19-post-repair.json`):

| floor | agreement | accept_hit | accept_miss | reject_hit | reject_avoided |
|---|---|---|---|---|---|
| 0.55–0.60 | 0.9138 | 4 | 0 | 5 | 49 |
| **0.65** | **0.9828** | 4 | 0 | 1 | 53 |
| 0.70–0.85 | 0.9828 | 4 | 0 | 1 | 53 |

The floor had been held at 0.60 because "every scholar-confirmed match
scores in [0.60, 0.65)" (sweep of 2026-07-12, below). #97/#98 showed that
those four matches were the wrong person every time (Ekkehard of Aura →
Ermengarde of Anjou, Fulcher of Chartres → Charles of Denmark, Tancred →
Constance of Toulouse, Ekkehard → Erard I of Brienne): a partial given-name
match at 0.62 is not a confirmation, it is the failure mode. With those
pairs re-adjudicated to reject, the [0.60, 0.65) band contains **no**
accepted pair, and across the whole corpus it held 215 links — places,
months, common words and wrong persons, not one correct link. 0.65 removes
four of the five rejected proposals the linker still makes; the fifth
("Fulcher of Chartres" → Charles of Denmark at exactly 0.65) is an
authority-coverage gap (#92), not a threshold question.

The four accepted matches all score 1.00 (exact name matches to the records
#45 added), so no floor up to 0.85 costs one of them. 0.65 is the smallest
step the data supports; go higher only when enrichment (#91) produces
correct matches below 0.75 to measure against.

### Superseded reasoning (2026-07-12 sweep, pre-repair gold)

| floor | agreement | accept_hit | accept_miss | reject_hit | reject_avoided |
|---|---|---|---|---|---|
| 0.60 | 0.8545 | 4 | 5 | 3 | 43 |
| 0.65 | 0.8000 | 0 | 9 | 2 | 44 |
| 0.70 | 0.8182 | 0 | 9 | 1 | 45 |
| 0.75–0.85 | 0.8182 | 0 | 9 | 1 | 45 |

Read today, the "accept_hit 4" column is the wrong-person pairs above.

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
