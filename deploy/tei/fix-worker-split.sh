#!/usr/bin/env bash
# Correct a split introduced on 2026-08-29 (#123 → #135). Run AS ROOT.
#
# root-install.sh enabled outremer-worker.timer and removed the interim cron.
# But the packaged worker only runs run_pipeline.py: no git pull, no
# provenance gate, no publish, and its source directory was never seeded.
# The interim nightly.sh does all of that and is proven. Until the packaged
# worker gains those stages (#135), the split is:
#
#   interim cron  → owns the nightly (pull, preflight, run, GATE, publish)
#   packaged web  → serves the site the nightly produces
#   packaged timer→ masked, so it cannot run a gate-less pipeline
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

WORKSITE=/home/dh/outremer/work/site

echo "== 1. stop the gate-less packaged worker =="
systemctl disable --now outremer-worker.timer 2>/dev/null || true
systemctl mask outremer-worker.service 2>/dev/null || true
echo "   outremer-worker.timer disabled, service masked (#135 re-enables it)"

echo "== 2. serve the site the nightly actually updates =="
# The packaged web unit pointed at /var/lib/outremer/state/site, a one-time
# seed that nothing refreshes; dh cannot write there by design.
if [ -d "$WORKSITE" ]; then
  sed -i "s#--directory /var/lib/outremer/state/site#--directory $WORKSITE#" \
      /etc/systemd/system/outremer-web.service
  # ProtectHome=true would hide /home from the unit
  sed -i 's/^ProtectHome=true/ProtectHome=read-only/' /etc/systemd/system/outremer-web.service
  systemctl daemon-reload
  systemctl restart outremer-web.service
  sleep 2
  systemctl is-active outremer-web.service
else
  echo "!! $WORKSITE missing — left web unit untouched"; exit 1
fi

echo "== 3. verify =="
curl -s -o /dev/null -w "   loopback  → HTTP %{http_code}\n" -m 10 http://127.0.0.1:8088/
curl -s -o /dev/null -w "   public    → HTTP %{http_code}\n" -m 10 https://tei.dh.unibe.ch/outremer/
echo "   crontab (as dh):"; crontab -u dh -l | grep -c outremer
echo "done"
