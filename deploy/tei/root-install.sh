#!/usr/bin/env bash
# Root installation for outremer on tei.dh.unibe.ch (#123, Epic 20).
# Run AS ROOT, from a checkout of thodel/outremer at the release commit:
#   sudo bash deploy/tei/root-install.sh
#
# Idempotent: safe to re-run. It performs ONLY the steps that require root and
# migrates the interim user-level deployment (~dh/outremer, crontab) into the
# #118 layout. It does NOT edit the nginx server block automatically — it
# stages the fragment and prints the include line, because the TLS block is
# shared with other services (ADR 0001: humans own the nginx topology).
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
REL=/opt/outremer/releases/$(cd "$REPO_ROOT" && git rev-parse --short HEAD)

echo "== 1. account + directories =="
id outremer >/dev/null 2>&1 || useradd --system --home-dir /var/lib/outremer --shell /usr/sbin/nologin outremer
install -d -o root -g outremer -m 0750 /etc/outremer
install -d -o outremer -g outremer -m 0750 /var/lib/outremer /var/lib/outremer/state /var/lib/outremer/source /var/cache/outremer
install -d -o root -g root -m 0755 /opt/outremer /opt/outremer/releases

echo "== 2. release checkout =="
if [ ! -d "$REL" ]; then
  git clone -q "$REPO_ROOT" "$REL"
  python3.12 -m venv "$REL/.venv"
  "$REL/.venv/bin/pip" install -q -r "$REL/requirements.lock.txt"
  "$REL/.venv/bin/pip" install -q -e "$REL" --no-deps
fi

echo "== 3. environment (migrated from the interim user deployment) =="
if [ ! -f /etc/outremer/outremer.env ]; then
  if [ -f /home/dh/outremer/etc/outremer.env ]; then
    cp /home/dh/outremer/etc/outremer.env /etc/outremer/outremer.env
    # state paths for the packaged layout (interim file points into the checkout)
    cat >> /etc/outremer/outremer.env <<'ENVEOF'
OUTREMER_SOURCE_DIR=/var/lib/outremer/source
OUTREMER_SITE_DIR=/var/lib/outremer/state/site
OUTREMER_BIB_DIR=/var/lib/outremer/state/bib
OUTREMER_EVIDENCE_DIR=/var/lib/outremer/state/evidence
OUTREMER_ENTITY_FEEDBACK_PATH=/var/lib/outremer/state/entity_feedback.json
OUTREMER_REVIEW_DECISIONS_PATH=/var/lib/outremer/state/decisions.json
ENVEOF
  else
    echo "!! no interim env found — copy outremer.env.example and fill it"; exit 1
  fi
fi
chown root:outremer /etc/outremer/outremer.env && chmod 0640 /etc/outremer/outremer.env

echo "== 4. state seed =="
[ -e /var/lib/outremer/state/site ] || cp -r "$REL/site" /var/lib/outremer/state/site
chown -R outremer:outremer /var/lib/outremer/state

echo "== 5. systemd units =="
# NOTE: rendered units ship MemoryMax=8G; tei has 3.8G RAM. Cap lower here.
for u in outremer-web.service outremer-worker.service outremer-worker.timer; do
  sed 's/^MemoryMax=8G/MemoryMax=2G/' "$HERE/rendered-tei/$u" > "/etc/systemd/system/$u"
done
ln -sfn "$REL" /opt/outremer/current
systemctl daemon-reload
systemctl enable --now outremer-web.service
systemctl enable --now outremer-worker.timer

echo "== 6. nginx (staged, manual include) =="
install -o root -g root -m 0644 "$HERE/rendered-tei/outremer.nginx.conf" /etc/nginx/snippets/outremer.conf
echo
echo "ADD inside the tei.dh.unibe.ch TLS server block:"
echo "    include snippets/outremer.conf;"
echo "then: nginx -t && systemctl reload nginx"
echo
echo "== 7. retire the interim cron (run as dh) =="
echo "    crontab -l | grep -v 'outremer/work/deploy/tei' | crontab -"
echo
echo "done — verify: systemctl status outremer-web outremer-worker.timer"
