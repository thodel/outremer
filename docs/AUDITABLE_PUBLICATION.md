# Auditable publication profiles and review

Run:

```bash
python3 scripts/evidence_publish.py fixtures/evidence-first/representative.json /tmp/outremer-publication
```

The versioned outputs are canonical JSON, lossless JSON-LD, Turtle, a clearly
labelled lossy schema.org discovery projection, and TEI stand-off mention links.
Every graph resource has a stable `https://outremer.example/id/...` URI.
Assertion and decision triples expose evidence and provenance; an embedded
canonical representation guarantees exact round-trip of locators, uncertainty,
temporal bounds, candidate scores, rejected decisions, and history.

`owl:sameAs` is emitted only when an accepted decision explicitly carries
`same_as_assertion: true`; imported identifiers or fuzzy scores cannot trigger
it.

The static `site/evidence-review.html` interface reviews both assertions and
identity hypotheses. Accept, reject, flag, comment, and supersede operations
create append-only JSONL decisions with pseudonymous reviewers and timestamps.
Concurrent accept/reject or accept/flag decisions remain visibly conflicted.
Source passages and imported records are never modified.

The existing `data/decisions.json` is outside this workflow and remains
untouched until an explicit reviewed migration.
