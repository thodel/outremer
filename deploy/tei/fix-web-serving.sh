#!/usr/bin/env bash
# Restore correct site serving after the mis-step in fix-worker-split.sh.
# Run AS ROOT.
#
# That script repointed the web unit at /home/dh/outremer/work/site. The unit
# runs as `outremer`, and /home/dh is mode 0750 dh:dh — the process cannot
# traverse into it, so every request 404s. Opening /home would be the wrong
# trade. Correct arrangement, and the one #118 intended:
#
#   web unit  serves /var/lib/outremer/state/site   (as `outremer`)
#   nightly   rsyncs its build into that directory  (as `dh`, via group write)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

UNIT=/etc/systemd/system/outremer-web.service
STATE=/var/lib/outremer/state/site

echo "== 1. serve state again, restore home protection =="
sed -i "s#--directory /home/dh/outremer/work/site#--directory $STATE#" "$UNIT"
sed -i 's/^ProtectHome=read-only/ProtectHome=true/' "$UNIT"
grep -E "ExecStart|ProtectHome" "$UNIT"

echo "== 2. let the nightly (user dh) write into the served directory =="
id -nG dh | tr ' ' '\n' | grep -qx outremer || usermod -aG outremer dh
install -d -o outremer -g outremer -m 2775 "$STATE"
chown -R outremer:outremer "$STATE"
chmod -R g+w "$STATE"
echo "   dh is now in group outremer; $STATE is group-writable (setgid)"

echo "== 3. seed it from the current build so the site is not empty =="
if [ -d /home/dh/outremer/work/site ]; then
  rsync -a --delete --exclude '.git' /home/dh/outremer/work/site/ "$STATE"/
  chown -R outremer:outremer "$STATE"; chmod -R g+w "$STATE"
fi

systemctl daemon-reload && systemctl restart outremer-web.service
sleep 2
systemctl is-active outremer-web.service
curl -s -o /dev/null -w "   loopback → HTTP %{http_code}\n" -m 10 http://127.0.0.1:8088/
curl -s -o /dev/null -w "   public   → HTTP %{http_code}\n" -m 10 https://tei.dh.unibe.ch/outremer/
echo
echo "NOTE: dh's new group membership needs a fresh login/cron cycle to take"
echo "effect. Tonight's cron run gets it; an interactive shell needs re-login."
