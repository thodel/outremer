#!/usr/bin/env bash
# Nightly outremer worker on tei.dh.unibe.ch (cron; see deploy/tei/README.md).
#
# Order matters: the provenance gate runs BEFORE anything is committed, so a
# degraded run (heuristic/mixed extraction, fallback chunks, wrong model)
# aborts and publishes nothing — the inverse of the retired Actions nightly,
# which silently published regex output for weeks.
set -euo pipefail

WORK="${OUTREMER_WORK:-$HOME/outremer/work}"
ENVFILE="${OUTREMER_ENV:-$HOME/outremer/etc/outremer.env}"
ETC="$(dirname "$ENVFILE")"
LOGDIR="$HOME/outremer/logs"
mkdir -p "$LOGDIR"

exec 9>"$HOME/outremer/.nightly.lock"
flock -n 9 || { echo "another run is active; skipping"; exit 0; }

cd "$WORK"
git pull --rebase origin main

set -a; . "$ENVFILE"; set +a
VENV="$WORK/.venv/bin"
"$VENV/pip" install -q -r requirements.lock.txt
"$VENV/pip" install -q -e . --no-deps

# 1) Capability preflight: GPUStack up, configured models actually exist.
"$VENV/python" scripts/release_control.py preflight \
  --config "$ETC/live-capabilities.json" \
  --output "$LOGDIR/preflight-latest.json"

# 2) The pipeline itself.
"$VENV/python" scripts/run_pipeline.py --llm-metadata

# 3) Provenance gate: refuse to publish anything the model did not produce.
"$VENV/python" scripts/release_control.py gate \
  --report data/staging/run_report.json \
  --output "$LOGDIR/gate-latest.json" \
  --expected-model "$EXTRACTION_MODEL"

# 4) Evaluation history (informational — never blocks publishing).
"$VENV/python" -m evaluation.harness --live \
  --append-history data/staging/eval_history.jsonl || true

# 5) Publish.
git add site/index.json site/data site/bib site/evidence bib \
        data/entity_feedback.json data/evidence data/staging/eval_history.jsonl
if git diff --cached --quiet; then
  echo "no changes to publish"
else
  git commit -m "chore: tei nightly — model-extracted site data [skip ci]"
  git pull --rebase origin main
  git push origin main
fi
