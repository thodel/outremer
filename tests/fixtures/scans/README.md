# Scanned recognition fixtures

Two image-only PDFs (no text layer) that exercise the real low-text-yield
recognition route. Both derive from the public-domain Wikimedia Commons image:

- *Magna Carta (British Library Cotton MS Augustus II.106)* — one of the four
  surviving 1215 exemplars
- Source: https://commons.wikimedia.org/wiki/File:Magna_Carta_(British_Library_Cotton_MS_Augustus_II.106).jpg
- Licence: public domain

## `magna-carta-1215-image-only.pdf` — routing fixture (1280 px derivative)

Wikimedia's 1280 px derivative embedded as a one-page image-only PDF. **It is
too coarse to recognise**: the sheet carries ~76 text lines in 853 px, i.e.
**~11 px per line**, where kraken/TrOCR want ~100 px and `qwen3-vl` refuses
outright (see #124). Keep it for what it does test — PDF detection, routing,
and run-report provenance — and do not draw quality conclusions from it.

## `magna-carta-1215-incipit-hires.pdf` — recognition fixture (full resolution)

The top band of the **7200×4800 original** (opening ~12 lines, left 65% of the
width), embedded unscaled: **4680×820, ~62 px per line** — 5.6× the linear
detail of the derivative, at 729 KB. Width is cropped rather than the image
downscaled, because line height is the quantity that decides legibility.

`magna-carta-1215-incipit.reference.txt` holds the corresponding published
Latin text of the charter's opening (an independent scholarly edition, so
absolute CER against it is legitimate — unlike CER against a Human-in-the-Loop
selection, see `evaluation/README.md`).

### What the live test asserts

Recognition is garbled at this hand: measured with `qwen3-vl-30b-a3b-instruct`,
"Johannes Dei gracia" does not survive, while `Steph… Archiep` (Stephen Langton,
in the preamble's witness list) does. Exact substring matching is therefore too
brittle. The live test instead asserts the transcription is **closer to this
charter than to an unrelated control text** — a relative comparison that
tolerates character noise but still fails on refusal, empty output, or noise.

Set `OUTREMER_LIVE_OCR=1` to run it; it needs GPUStack reachability, i.e. a
host inside the university network.
