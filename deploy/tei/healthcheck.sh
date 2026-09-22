#!/usr/bin/env bash
# Morning healthcheck for the outremer nightly (#115). Cron: 08:00.
#
# Checks, in order of "did anything at all happen" to "was it any good":
#   1. nightly.log was written within the last 30h
#   2. the provenance gate passed
#   3. the published status file agrees (0 fallback chunks)
#   4. weekly: scanned-page recognition still reads the hi-res fixture
# On failure: writes an ALERT file into the log dir and a syslog line via
# logger(1). Channel escalation (mail/Discord) is an operator decision —
# see #115; this script is the hook to attach it to.
set -u
LOGDIR="$HOME/outremer/logs"
FAILS=""

if [ ! -f "$LOGDIR/nightly.log" ] || [ -n "$(find "$LOGDIR/nightly.log" -mmin +1800)" ]; then
  FAILS="$FAILS nightly.log-missing-or-stale;"
fi
GATE=$(python3 -c "import json;print(json.load(open('$LOGDIR/gate-latest.json')).get('status','?'))" 2>/dev/null || echo unreadable)
[ "$GATE" = "pass" ] || FAILS="$FAILS gate=$GATE;"
FB=$(python3 -c "import json;print((json.load(open('$HOME/outremer/work/site/data/status.json')).get('run') or {}).get('fallback_chunks'))" 2>/dev/null || echo unreadable)
[ "$FB" = "0" ] || FAILS="$FAILS fallback_chunks=$FB;"

# 4. OCR canary. Every nightly document has a text layer, so recognition is
# never exercised: from 2026-09-07 to 2026-09-22 it returned empty text (a
# reasoning model in thinking mode, #141) while every nightly stayed green.
# Run the live recognition test once the last pass is a week old; a failure
# repeats (and alerts) every morning until fixed. "1 passed" is checked, not
# just the exit code, so a skipped or deselected test cannot count as health.
CANARY_OK="$LOGDIR/ocr-canary.ok"
if [ ! -f "$CANARY_OK" ] || [ -n "$(find "$CANARY_OK" -mtime +6)" ]; then
  (
    cd "$HOME/outremer/work" || exit 1
    set -a; . "${OUTREMER_ENV:-$HOME/outremer/etc/outremer.env}"; set +a
    OUTREMER_LIVE_OCR=1 timeout 1200 .venv/bin/python -m pytest -q \
      -p no:cacheprovider tests/test_scanned_recognition.py -k live_hires
  ) >"$LOGDIR/ocr-canary.log" 2>&1
  if grep -q "1 passed" "$LOGDIR/ocr-canary.log"; then
    touch "$CANARY_OK"
  else
    FAILS="$FAILS ocr-canary-failed(see ocr-canary.log);"
  fi
fi

if [ -n "$FAILS" ]; then
  STAMP=$(date +%Y-%m-%d)
  echo "$(date -Is) outremer nightly UNHEALTHY:$FAILS" | tee -a "$LOGDIR/ALERT-$STAMP"
  logger -t outremer-healthcheck "UNHEALTHY:$FAILS"
  exit 1
fi
echo "$(date -Is) healthy"
exit 0
