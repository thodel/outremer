#!/usr/bin/env bash
# Move the outremer nightly from dh's crontab to the packaged systemd timer (#134).
# Run AS ROOT, from the work checkout:
#     sudo bash /home/dh/outremer/work/deploy/tei/worker-on-nightly.sh
#
# What it does, and nothing else:
#   1. renders outremer-worker.service/.timer from this checkout's templates
#      (the worker now runs deploy/tei/nightly.sh as dh — gate before publish)
#   2. installs them, unmasks the service fix-worker-split.sh had masked,
#      verifies the units, enables the timer (03:15 Europe/Zurich)
#   3. removes the nightly line from dh's crontab; the healthcheck line stays
# It does not start a run. A cron run and a timer run cannot overlap anyway:
# nightly.sh takes a flock and the second one exits "another run is active".
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== 1. render =="
python3 "$HERE/render_config.py" --output-dir "$TMP" >/dev/null
grep -q "^ExecStart=/bin/bash .*/deploy/tei/nightly.sh$" "$TMP/outremer-worker.service" \
  || { echo "!! rendered worker does not run nightly.sh — aborting"; exit 1; }

echo "== 2. install + verify + enable =="
for u in outremer-worker.service outremer-worker.timer; do
  [ -f "/etc/systemd/system/$u" ] && cp "/etc/systemd/system/$u" "/etc/systemd/system/$u.bak-$(date +%Y%m%d)" || true
  install -o root -g root -m 0644 "$TMP/$u" "/etc/systemd/system/$u"
done
# the .bak copies must not look like units: move them out of the unit directory
mkdir -p /root/outremer-unit-backups && mv /etc/systemd/system/outremer-worker.*.bak-* /root/outremer-unit-backups/ 2>/dev/null || true
systemctl unmask outremer-worker.service >/dev/null 2>&1 || true
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/outremer-worker.service /etc/systemd/system/outremer-worker.timer
systemctl enable --now outremer-worker.timer

echo "== 3. retire the nightly cron line (healthcheck stays) =="
if crontab -u dh -l 2>/dev/null | grep -q 'deploy/tei/nightly.sh'; then
  crontab -u dh -l | grep -v 'deploy/tei/nightly.sh' | crontab -u dh -
  echo "   removed"
else
  echo "   not present"
fi

echo "== verify =="
systemctl list-timers outremer-worker.timer --no-pager
echo "crontab dh:"; crontab -u dh -l | grep -n outremer || true
echo "done — next run at 03:15; afterwards: journalctl -u outremer-worker; tail /home/dh/outremer/logs/nightly.log"
