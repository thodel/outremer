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
# The MCP server (Epic 22) runs from this venv as a dh user unit; its only
# extra dependency is kept here so a rebuilt venv does not silently drop it
# (2026-10-15: `import mcp` had resolved to a stray directory, not a package).
"$VENV/pip" install -q "mcp>=2.0.0,<3"

# 0) Adjudications (M13.3, #179): carry new review-API events into
#    data/decisions.json and rebuild the gold fixtures from them, so a decision
#    made in the Explorer counts in tonight's harness and is published as a
#    diff below. The API is a dh user unit on loopback; if it is down, the
#    night goes on without new gold and says so.
if "$VENV/python" scripts/import_review_decisions.py \
     --url "${REVIEW_API_URL:-http://127.0.0.1:8089}" \
     --decisions data/decisions.json | tee "$LOGDIR/review-import-latest.log"; then
  if ! git diff --quiet -- data/decisions.json; then
    "$VENV/python" -m evaluation.build_fixture --relink
  fi
else
  echo "::warning::review import failed — adjudications stay as they were (see review-import-latest.log)"
fi

# 1) Capability preflight: GPUStack up, configured models actually exist.
"$VENV/python" scripts/release_control.py preflight \
  --config "$ETC/live-capabilities.json" \
  --output "$LOGDIR/preflight-latest.json"

# 2) The pipeline itself — under the air-gap guard (M17.3): every outbound
#    connection except GPUStack, the ATR gateway and the MCP base host is
#    refused inside the process, so a new outbound dependency fails here,
#    before the gate, and publishes nothing.
"$VENV/python" scripts/run_pipeline.py --llm-metadata --airgap

# 3) Provenance gate: refuse to publish anything the model did not produce.
"$VENV/python" scripts/release_control.py gate \
  --report data/staging/run_report.json \
  --output "$LOGDIR/gate-latest.json" \
  --expected-model "${GPUSTACK_MODEL_TEXT:-$EXTRACTION_MODEL}"

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
  # -O (omit-dir-times): the directories are owned by `outremer` too, so
  # setting their mtime fails the same way. Without -O every night ended in
  # "failed to set times" + exit 23 and the warning below, although all files
  # had arrived (log 2026-08-30 … 2026-10-14).
  if rsync -rlptDO --delete --exclude '.git' site/ "$PUBLIC_SITE"/; then
    echo "mirrored site/ → $PUBLIC_SITE"
  else
    # The mirror is a view; the git publish below is the durable record.
    # A failed mirror must never cost the publish.
    echo "::warning::site mirror failed — public page may be stale"
  fi
else
  echo "note: $PUBLIC_SITE not writable — public site not refreshed"
fi

# 5) Publish. decisions.json and the fixtures ride in the same commit as the
#    run they first counted in (M13.3): the diff is the audit trail.
git add site/index.json site/data site/bib site/evidence bib \
        data/entity_feedback.json data/evidence data/staging/eval_history.jsonl \
        data/decisions.json evaluation/fixtures
if git diff --cached --quiet; then
  echo "no changes to publish"
else
  git commit -m "chore: tei nightly — model-extracted site data [skip ci]"
  git pull --rebase origin main
  git push origin main
fi
