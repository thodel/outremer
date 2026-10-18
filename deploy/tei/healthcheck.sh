#!/usr/bin/env bash
# Morning healthcheck for the outremer nightly (#115). Cron: 08:00.
#
# Checks, in order of "did anything at all happen" to "was it any good":
#   1. nightly.log was written within the last 30h
#   2. the provenance gate passed
#   3. the published status file agrees (0 fallback chunks)
#   4. weekly: scanned-page recognition still reads the hi-res fixture
#   5. the MCP server (Epic 22) answers, locally and through nginx, and serves
#      gate-checked data only (#131)
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
# Run evaluation/ocr_canary.py once the last pass is a week old; a failure
# repeats (and alerts) every morning until fixed. It runs the production reader
# with no dev dependencies — the venv here is installed from the lockfile and
# has no pytest, which is exactly what broke the first, pytest-based version.
# The printed verdict is checked, not just the exit code.
CANARY_OK="$LOGDIR/ocr-canary.ok"
if [ ! -f "$CANARY_OK" ] || [ -n "$(find "$CANARY_OK" -mtime +6)" ]; then
  (
    cd "$HOME/outremer/work" || exit 1
    set -a; . "${OUTREMER_ENV:-$HOME/outremer/etc/outremer.env}"; set +a
    timeout 1200 .venv/bin/python -m evaluation.ocr_canary --save "$LOGDIR/ocr-canary.txt"
  ) >"$LOGDIR/ocr-canary.log" 2>&1
  if grep -q '"canary": "pass"' "$LOGDIR/ocr-canary.log"; then
    touch "$CANARY_OK"
  else
    FAILS="$FAILS ocr-canary-failed(see ocr-canary.log);"
  fi
fi

# 5. MCP server (#131). Local first: the dh user unit outremer-mcp on :8014.
# Then the public route nginx adds; a 404 there means the location is missing,
# a 502 that nginx cannot reach the unit. The body must say ok, name records,
# carry the gate verdict of the data it serves, and withhold nothing — a
# withheld document means the server is pointed at ungated output (#178).
MCP_LOCAL="${OUTREMER_MCP_HEALTH:-http://127.0.0.1:8014/health}"
MCP_PUBLIC="${OUTREMER_MCP_PUBLIC_HEALTH:-https://tei.dh.unibe.ch/mcp/outremer/health}"
mcp_verdict() {
  curl -s -m 10 "$1" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("unreadable"); sys.exit()
bad = []
if d.get("status") != "ok": bad.append("status=%s" % d.get("status"))
if not d.get("records"): bad.append("records=%s" % d.get("records"))
if d.get("gate") != "pass": bad.append("gate=%s" % d.get("gate"))
if d.get("withheld"): bad.append("withheld=%s" % d.get("withheld"))
print(",".join(bad) or "ok")' 2>/dev/null || echo unreachable
}
V=$(mcp_verdict "$MCP_LOCAL"); [ "$V" = "ok" ] || FAILS="$FAILS mcp-local($V);"
# curl prints 000 itself when nothing answered; `|| echo 000` would append a second.
CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 10 "$MCP_PUBLIC" 2>/dev/null)
CODE=${CODE:-000}
if [ "$CODE" = "200" ]; then
  V=$(mcp_verdict "$MCP_PUBLIC"); [ "$V" = "ok" ] || FAILS="$FAILS mcp-public($V);"
else
  FAILS="$FAILS mcp-public=HTTP$CODE;"
fi

if [ -n "$FAILS" ]; then
  STAMP=$(date +%Y-%m-%d)
  echo "$(date -Is) outremer nightly UNHEALTHY:$FAILS" | tee -a "$LOGDIR/ALERT-$STAMP"
  logger -t outremer-healthcheck "UNHEALTHY:$FAILS"
  exit 1
fi
echo "$(date -Is) healthy"
exit 0
