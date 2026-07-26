# Provenance, uncertainty, time and place

The v1 semantics keep distinct fields for:

- source wording and `source_certainty`
- polarity (`affirmed`, `negated`, `disputed`)
- inference (`source_explicit`, `source_implicit`, `extracted`, `editorial_inference`)
- source reliability (`high`, `medium`, `low`, `unassessed`)
- extractor confidence, reconciliation score, and editorial confidence
- review status (`unreviewed`, `accepted`, `rejected`, `disputed`, `superseded`)

These dimensions must not be collapsed into one confidence number.

Assertion time is separate from source creation/publication, ingestion,
generation, and review times. It supports `when`, `from/to`,
`notBefore/notAfter`, open intervals, original textual dating, and calendar or
normalization notes.

Place strings remain attached to assertions. Ranked place candidates preserve
their own URI, temporal scope, geometry, and spatial precision. No candidate is
required, and multiple candidates may remain unresolved.

RDF uses PROV-O for snapshots, generation and review activities; CIDOC
CRM/CRMinf-compatible assertion resources; SKOS-like controlled terms; and
GeoSPARQL WKT for geometry. `schema/evidence-first-v1.shacl.ttl` rejects missing
evidence, malformed ranges, invalid decision status, and accepted identity
decisions without a reviewer-bearing review activity.
