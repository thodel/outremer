# Evidence-first canonical contract v1

The operational schema is `schema/evidence-first-v1.schema.json`, version
`1.0.0`. Its central rule is simple: adapters create evidence objects and
identity hypotheses; they never silently merge people.

The chain is:

`source_work → manifestation → snapshot → passage → mention/assertion`

Persons and groups are editorial identity nodes. An `identity_hypothesis`
connects a verbatim mention to ranked candidates. Decisions are immutable,
attributed review events. Rejection, dispute, and supersession add new objects;
they never delete the mention, assertion, candidate, or earlier decision.

Local IDs use `outremer:<type>:<stable-token>`. Generated IDs hash the object
type and stable source coordinates. Source-native identifiers remain in
`source_native_ids`; they are not used as proof that two identity nodes are the
same. Objects carry integer versions, optional `supersedes`, and optional
`tombstone` markers.

Every assertion has one or more passages. Every passage belongs to an immutable
checksum-bearing snapshot. Every mention preserves the exact text plus language
and script where known.

Run the read-only migration inventory with:

```bash
python3 scripts/migrate_evidence_model.py --output /tmp/migration-report.json
```

It inventories current authority, Wikidata, extraction, and quarantined DHI/FMG
structures and verifies that `data/decisions.json` is byte-for-byte unchanged.
