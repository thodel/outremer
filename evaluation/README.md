# Evaluation methodology

## Recognition selections are closest-reading evidence

A Human-in-the-Loop recognition choice means only that the scholar selected
the closest acceptable reading from the candidates the pipeline offered. It
is not an independently transcribed reference and must not be described as
ground truth or gold.

Selection-derived recognition evaluation therefore reports:

- **Coverage:** whether the candidate pool offered an acceptable reading.
- **Selection agreement:** whether the automatic choice matched the human
  choice among covered events.
- **Selection regret:** candidate-to-candidate CER between the automatic and
  human choices. This is a distance within the offered pool, not accuracy.
- **Relative engine preference:** pairwise human choices may later support
  routing priors by script, language, or century.

If every candidate contains the same error, selecting one does not make that
error correct. Absolute CER or WER requires a separately produced,
independent scholarly reference transcription. It must remain distinct from
selection data in both storage and terminology.

Recognition selection events use this shape:

```json
{
  "candidates": ["offered reading A", "offered reading B"],
  "automatic_selection": "offered reading A",
  "human_selection": "offered reading B"
}
```

`human_selection: null` records that no offered reading was usable. The
evaluation code rejects selection payloads whose fields make truth claims
using the forbidden names `ground_truth` or `gold`.
