#!/usr/bin/env bash
# Morning healthcheck for the outremer nightly (#115). Cron: 08:00.
#
# Checks, in order of "did anything at all happen" to "was it any good":
#   1. nightly.log was written within the last 30h
#   2. the provenance gate passed
#   3. the published status file agrees (0 fallback chunks)
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

if [ -n "$FAILS" ]; then
  STAMP=$(date +%Y-%m-%d)
  echo "$(date -Is) outremer nightly UNHEALTHY:$FAILS" | tee -a "$LOGDIR/ALERT-$STAMP"
  logger -t outremer-healthcheck "UNHEALTHY:$FAILS"
  exit 1
fi
echo "$(date -Is) healthy"
exit 0
