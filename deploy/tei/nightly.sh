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
# --autostash: a previous aborted run leaves regenerated pipeline output in
# the tree, and a plain rebase then refuses to start — which turns one
# failed night into every following night failing too.
git pull --rebase --autostash origin main

# Log hygiene (#115): cap the cron log, prune one-off run logs older than 14d.
if [ -f "$LOGDIR/nightly.log" ] && [ "$(wc -c < "$LOGDIR/nightly.log")" -gt 5242880 ]; then
  mv "$LOGDIR/nightly.log" "$LOGDIR/nightly.log.1"
fi
find "$LOGDIR" -maxdepth 1 -name "full-run-*.log" -mtime +14 -delete 2>/dev/null || true

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

# 4b) Published status file (#115): last run, engine mix, gate verdict —
# served by GitHub Pages, so no SSH is needed to check the nightly's health.
"$VENV/python" scripts/nightly_status.py \
  --gate "$LOGDIR/gate-latest.json" || true

# 4c) Mirror the freshly built site into the served state directory, so the
# public page reflects this run. The web unit runs as `outremer` and cannot
# read /home/dh (mode 0750) — hence a copy into shared state rather than
# pointing the server at the work tree. Requires group write, granted by
# deploy/tei/fix-worker-split.sh.
PUBLIC_SITE="${OUTREMER_PUBLIC_SITE:-/var/lib/outremer/state/site}"
if [ -d "$PUBLIC_SITE" ] && [ -w "$PUBLIC_SITE" ]; then
  # -rlptD is -a minus -o/-g: the destination belongs to the `outremer` user
  # and this runs as `dh`, so preserving ownership fails with EPERM. rsync
  # then exits 23 and, under `set -e`, killed the whole run *before* the
  # publish step — the files copied, but nothing reached GitHub (2026-08-30).
  # The setgid directory assigns the right group by itself.
  if rsync -rlptD --delete --exclude '.git' site/ "$PUBLIC_SITE"/; then
    echo "mirrored site/ → $PUBLIC_SITE"
  else
    # The mirror is a view; the git publish below is the durable record.
    # A failed mirror must never cost the publish.
    echo "::warning::site mirror failed — public page may be stale"
  fi
else
  echo "note: $PUBLIC_SITE not writable — public site not refreshed"
fi

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
