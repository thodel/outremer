# Syriaca.org snapshot pilot

The adapter consumes `srophe/syriaca-data` only at the full commit recorded in
`config/syriaca_snapshot.json`. A checkout is rejected unless `HEAD` equals that
commit. Every mapped record retains repository URL, commit, file path, SHA-256,
adapter version, Syriaca URI, `xml:id`, multilingual names/scripts, dates,
relations, events, bibliography/source pointers, revision history, and its own
availability statement.

SPEAR factoids become source assertions with their locators. They are never
silently promoted to canonical truth. Third-party material mentioned inside a
CC BY record is flagged separately for review and attribution.

The pilot selection is reproducible: records must overlap 1000–1400 and mention
one configured Levant/connected-Mediterranean place term. Records without usable
dates remain candidates only when geographic evidence exists.

The documented live API, per-record TEI, and OAI endpoints are health-checked
separately. The live adapter is disabled; failures can never trigger a silent
switch away from the pinned repository snapshot.

## Attribution

Public output must name Syriaca.org, link the record URI, reproduce the
per-record licence target, cite the pinned repository commit, and flag any
incorporated third-party material for a separate rights assessment.

## Review workload

`data/pilots/syriaca/reconciliation_report.json` records the initial twenty-case
manual review: candidate, ambiguity class, decision, rationale, and estimated
curator effort. It is a pilot baseline, not an automated identity gold set.
