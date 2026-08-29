# TEI inside-network validation and release control

Issue #112 separates two fundamentally different execution environments:

- `.github/workflows/Epic5-CI.yml` remains offline and runs on GitHub-hosted
  workers without University of Bern credentials or network access.
- `.github/workflows/tei-live-release.yml` is manual-only and targets a runner
  carrying all three labels `self-hosted`, `linux`, and `outremer-tei` inside the
  university network.

The live workflow is inert until an infrastructure owner registers that runner,
creates protected `tei-staging` and `tei-production` GitHub environments, and
sets the environment variables below. Production must require human approval.
This repository contains no runner registration token or service credential.

## Required host/environment configuration

Both environments define non-secret GitHub environment variables:

- `OUTREMER_ENV_FILE`: absolute host path to the root-owned runtime environment;
- `OUTREMER_LIVE_CONFIG`: absolute host path to the reviewed capability config;
- `OUTREMER_RELEASE_ROOT`: production immutable release root (production environment);
- `OUTREMER_PRODUCTION_SMOKE_URL`: production URL including trailing slash.

The staging environment file supplies capability credentials/model names and:

- `OUTREMER_SOURCE_DIR`, `OUTREMER_STATE_DIR`, `OUTREMER_STAGING_DIR`;
- `OUTREMER_STAGING_SMOKE_URL`, including its trailing slash;
- GPUStack, ATR, and any enabled MCP/QLever/Voyant endpoint settings.

Start from `deploy/tei/live-capabilities.example.json`, store the resolved copy
outside the checkout, and review every `required` classification. Optional
services are recorded as unavailable but do not fail preflight. Required service
or storage failures block the release.

The runner identity needs no general sudo access. Permit only restart of the
named staging/production web units. It needs write access to its staging/release
roots and `/var/lock/outremer-release.lock`; pipeline and deployment identities
should remain separate where the host policy permits.

## Validation and provenance gates

One `validate` or `promote` dispatch performs, under a non-blocking host `flock`:

1. capability health/model discovery and storage/schema preflight;
2. a live text-layer run using GPUStack;
3. a live image-only scan run using the configured recognition backend;
4. strict run-report gates requiring all documents to succeed, `gpustack` as
   the only extraction engine, zero fallback chunks, the resolved extraction
   model, and a recorded recognition engine for the scan;
5. immutable manifest creation and staging release installation in a run-specific root;
6. atomic staging pointer switch and smoke checks for representative assets.

The manifest records commit/tree, optional image digest, lock-file digest,
installed dependency versions, Python version, resolved role models, sanitized
endpoints, capability/model versions, evidence schema/migration state, and
digests plus gate results for both live reports. Secret-like keys are forbidden,
credentials never enter the result, and a dirty tracked checkout cannot produce
a manifest.

`scripts/release_control.py` can be run manually for diagnosis:

```bash
python scripts/release_control.py preflight \
  --config /etc/outremer/live-capabilities.json \
  --output /var/lib/outremer/staging/preflight.json

python scripts/release_control.py gate \
  --report data/staging/run_report.json \
  --expected-model "$EXTRACTION_MODEL" \
  --require-recognition \
  --output /var/lib/outremer/staging/gate.json
```

These reports may contain internal endpoint topology. Keep them on university
storage; the workflow deliberately does not upload them as GitHub artifacts.

## Promotion

Choosing `promote` first completes all staging validation. Only then does the
`tei-production` job become eligible for its human approval. It verifies that
the exact staged directory name matches the checked-out 40-character commit,
copies that immutable release if necessary, atomically switches `current`,
records a digest-linked JSONL history event, restarts the named web unit, and
smoke-tests `index.html` and `app.js`.

The workflow concurrency group never cancels an in-progress run. The same host
lock prevents overlap with manual/scheduled pipeline work. Operators must make
other pipeline entry points use `/var/lock/outremer-release.lock` as well.

## Rollback

Rollback is a separate `rollback` dispatch and always crosses the protected
production environment. Supply a full 40-character commit for a previously
verified release already present beneath `RELEASE_ROOT/releases/`. The helper
rejects arbitrary paths, missing/dirty/non-production manifests, or a directory
whose name differs from its manifested commit. It atomically switches `current`,
appends the history event, restarts the web service, and smoke-tests it.

This is application rollback. If a future release changes mutable-state schema,
the state compatibility and restore procedure from #111/#114 must run before an
older application is selected.

## Failure semantics

- No required backend, model, schema, or writable storage: stop before inference.
- Heuristic/mixed extraction, fallback chunks, failed/empty documents, wrong
  model, or missing scan recognition: stop before manifest and promotion.
- Staging smoke failure: keep the release for diagnosis; do not expose production.
- Production smoke failure: the job fails visibly; use the protected rollback
  action rather than silently switching state inside the failing job.
- Lock contention: stop immediately rather than cancel or overlap expensive work.

Issue #115 adds monitoring and periodic synthetic checks. Issue #85 adds the
complementary allowed-network/air-gap assertion.
