# Linker operating point (M10.3)

Thresholds are config-backed (`scripts/config.py`, env-overridable):

| setting | value | meaning |
|---|---|---|
| `LINK_CANDIDATE_FLOOR` | 0.75 | minimum ensemble score to appear as a candidate |
| `LINK_MEDIUM` | 0.75 | status "medium" (the "low" band no longer exists) |
| `LINK_HIGH` | 0.90 | status "high" |

## The operating point since 2026-10-10 (M19.3, #93)

Two decisions, both from listing every corpus link and judging it, because
the gold cannot see them: all 14 accepts score 1.00 and no reject scores
above 0.88, so the fixture sweep is flat between 0.65 and 0.75.

**1. Floor 0.65 → 0.75.** The band [0.65, 0.75) held 41 links relinked
against the current documents; one was correct ("Pope Urban" → Urban II,
0.69). *Saladin* → Baldwin of Vern d'Anjou 0.71, *Bernard of Clairvaux* →
Bernard of Dorat 0.72, *Islam* → William the Huntsman 0.67 are what the band
looked like. Since `LINK_MEDIUM` is 0.75 as well, the status "low" is gone.

**2. Bare given names no longer match on their own.** Of the 23 links at
1.00, nine were a bare mention — *Robert*, *Baldwin*, *Godfrey*, *Matthew*,
*Walter*, *Bernard* — matching the bare Omeka-generated variant of an
arbitrary record: Munro's Godfrey of Bouillon became Godfrey III of Louvain
at full confidence, and the Explorer's TEI export calls 1.00 "high"
certainty. 145 of the 592 Omeka variants are such forms (eight records share
"william", eight "hugh"). `linker.build_authority_lookup` now skips a bare
form unless its provenance entry says `"bare": "attested"` — three do:
*Tancred* (CR200), *Ekkehard* (CR189), *Godfrey* (CR184), each listed by a
person for a corpus in which the bare name means that man.

| | before (#165) | floor 0.75 | + bare rule |
|---|---|---|---|
| corpus links high / medium / low | 23 / 45 / 41 | 23 / 45 / — | **16 / 14 / —** |
| correct among high | 14 of 23 | 14 of 23 | **16 of 16** |
| correct among medium | 2 of 45 | 2 of 45 | 2 of 14 |
| fixtures: accept hit / reject still proposed | 14 / 4 | 14 / 4 | 14 / 3 |
| agreement / lift over null | 0.9437 / +0.141 | 0.9437 / +0.141 | **0.9577 / +0.155** |

Fixture sweep after both changes (`python -m evaluation.sweep`):

| floor | agreement | accept_hit | reject_hit |
|---|---|---|---|
| 0.65–0.75 | 0.9577 | 14 | 3 |
| 0.80 | 0.9859 | 14 | 1 |
| 0.90 | 1.0000 | 14 | 0 |

A floor of 0.80 or 0.90 would read better on the gold and worse for the
project: the medium band (14 links, 12 wrong, all string similarity on a
shared given name — the eight *Robert …* → Robert II of Flanders at 0.77)
is the review queue that grows the gold (Part 2 of the worksheet), and the
remaining wrong matches are a ranking problem, not a threshold one: that is
Epic 21 (reranker, #126). CI gates on `--min-lift 0.10` from here, a "do not
regress below 2026-10-10" floor under the measured +0.155.

Baseline band (deterministic under `--relink`): combined 0.9195 over 87
pairs, 3 repeats, range 0.9195–0.9195 — `evaluation/baselines/epic19-post-repair.json`.

### Superseded: why the floor was 0.65 (2026-10-09)


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
