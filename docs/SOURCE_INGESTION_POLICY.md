# External source ingestion policy

`data/sources/registry.json` is the authority for whether external material may
enter canonical or public Outremer outputs. Technical accessibility is not
permission.

Adapters must call `require_operation(source_id, operation)` before fetching,
transforming, or publishing. Unknown sources fail closed. Only
`open-integrable` sources may pass without a non-empty written-permission record.
Application-code licensing and data/content licensing are recorded separately.

Legacy DHI and FMG samples remain in place for parser tests, but
`data/quarantine/manifest.json` excludes them from canonical and public builds.
They must not be refreshed or published while their decision remains
`permission-required`.

The weekly review reports stale entries. It never changes a rights decision
automatically. If terms change, an endpoint dies, or a custodian requests
withdrawal, disable export immediately, preserve the last snapshot in quarantine
for audit, record the reason, and contact the source custodian.
