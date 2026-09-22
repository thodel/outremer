# Recognition comparison: Magna Carta 1215, page-shaped crop (M14.5, #124)

One scanned page through both recognition paths, each transcript stored with
its engine provenance (`provenance.json`). Run on tei, inside the university
network, on 2026-09-22 at 07:37 CEST:

```bash
python -m evaluation.recognition_compare \
  tests/fixtures/scans/magna-carta-1215-incipit-page.pdf \
  --engine vlm \
  --engine kraken:kraken-catmus_medieval \
  --engine trocr:trocr-essoins-middle-latin \
  --out evaluation/recognition/magna-carta-1215-incipit-page
```

**Input.** `magna-carta-1215-incipit-page.pdf`, 1230×820 px: the left edge of
the charter's opening ~12 lines at ~62 px per line. Every line is cut at the
right edge, so **no reference text matches it, and nothing here is an accuracy
figure.**

## Engines and what their ids really load

| file | path | model id | weights | chars | time |
|---|---|---|---|---|---|
| `vlm.txt` | GPUStack | `qwen3.8-27b` | (served model) | 502 | 13.1 s |
| `kraken__kraken-catmus_medieval.txt` | ATR `/ocr` | `kraken-catmus_medieval` | Zenodo `10.5281/zenodo.7516057` | 384 | 30.9 s |
| `trocr__trocr-essoins-middle-latin.txt` | ATR `/ocr` | `trocr-essoins-middle-latin` | HF `dh-unibe/trocr-essoins-middle-latin` | 605 | 35.3 s |

**The kraken id is misleading.** Zenodo 7516057 is *"HTR Model – Medieval Latin
and French 12th–15th c. expanded (no abbr.)"* (v1.0, CC BY 4.0), not CATMuS
Medieval. It is one of several gateway ids that name one model and load
another, which is why `provenance.json` records the weights as well as the id.
The TrOCR model is trained on essoin rolls.

`service_version` is what each engine reports: the kraken library (7.0.2) and
the TrOCR service (0.1.0). The gateway returns no TrOCR confidence, so `0.0`
there means "not reported", not "no confidence".

## Candidate distance

| pair | distance |
|---|---|
| kraken ↔ TrOCR | 0.588 |
| kraken ↔ VLM | 0.598 |
| TrOCR ↔ VLM | 0.578 |

Symmetric edit distance over the longer normalised transcript. It measures how
much the engines **disagree**, not how well any of them reads. All three pairs
are far above `ENSEMBLE_NO_MERGE_CER = 0.35`, so fusing these transcripts
would average noise. **Epic 16 stays gated.**

## What the transcripts show (observations, not measurements)

- **All three read the same passages:** the left ends of the lines, from the
  witness list into clauses 1–4. For example, clause 4's *…discretis
  hominibus de feodo illo, qui de exitibus respondeant…* comes out as VLM `de.
  fedo. illo. qui. de. ex. u. b. re. spond.`, kraken `de feedo ilso qui de
  exitibz ra pondean`, and TrOCR `cretis hominibus de feodo illo qui de
  exitibus respondean`.
- **TrOCR is the most fluent, and it invents.** Between real lines it emits
  its training domain: `Quietus`, `suspendatur`, `misericordia`, `Et Thomas`,
  `Bedfordshire`. None of these is on the page. This is typical when a line
  model is fed empty or fragmentary segments.
- **kraken fragments.** Many of its lines are empty or a few letters long,
  which points to segmentation of the cut-off lines rather than recognition.
- **The VLM abbreviates heavily** and opens with noise (`100`, `I. C. A. A.`).
  On this page it stopped normally after 13 s. On the 4680×820 strip, the same
  model repeats `w.` up to its token limit (#73).

## Timing: page-shaped vs strip

kraken needed 30.9 s here. On 2026-08-29, a 6336×864 strip of the same
charter hit the gateway's 300 s budget and returned 502. kraken's `blla`
segmenter scales every input to a fixed height, so its cost follows the aspect
ratio, not the pixel count. The comparison tool therefore refuses ATR engines
for anything wider than 2.5:1.
