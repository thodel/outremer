#!/usr/bin/env bash
# Publish outremer at https://tei.dh.unibe.ch/outremer/ (#123, Epic 20).
# Run AS ROOT after root-install.sh has staged /etc/nginx/snippets/outremer.conf.
#
# The TLS server block is shared with other services (agentic_historian, the
# MCP fleet, Voyant), so this does the one edit it needs, verifies it, and
# rolls back automatically if nginx rejects the result. Idempotent.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

SITE=${SITE:-/etc/nginx/sites-available/tei.dh.unibe.ch}
SNIPPET=/etc/nginx/snippets/outremer.conf
LINE="    include snippets/outremer.conf;"

[ -f "$SNIPPET" ] || { echo "missing $SNIPPET — run root-install.sh first"; exit 1; }

if grep -q "snippets/outremer.conf" "$SITE"; then
  echo "include already present — nothing to do"
else
  BACKUP="$SITE.bak.$(date +%Y%m%d-%H%M%S)"
  cp -a "$SITE" "$BACKUP"
  echo "backup: $BACKUP"

  # Insert before the closing brace of the FIRST server block (the TLS one:
  # it is the block containing `listen 443 ssl`). awk tracks brace depth so a
  # reformatted file cannot silently put the include in the wrong block.
  awk -v line="$LINE" '
    BEGIN { depth = 0; inserted = 0; in_tls = 0; buf = "" }
    { buf = buf $0 "\n"
      if ($0 ~ /listen[[:space:]]+443[[:space:]]+ssl/) in_tls = 1
      n = gsub(/\{/, "{"); depth += n
      m = gsub(/\}/, "}"); depth -= m
      if (in_tls && !inserted && depth == 0) {
        sub(/\}\n$/, line "\n}\n", buf)
        inserted = 1
      }
    }
    END { printf "%s", buf; if (!inserted) exit 3 }
  ' "$BACKUP" > "$SITE" || { cp -a "$BACKUP" "$SITE"; echo "could not locate the TLS block — restored"; exit 3; }

  echo "inserted: $LINE"
fi

if nginx -t; then
  systemctl reload nginx
  echo "nginx reloaded"
else
  LATEST=$(ls -t "$SITE".bak.* 2>/dev/null | head -1)
  [ -n "$LATEST" ] && cp -a "$LATEST" "$SITE" && echo "config rejected — restored $LATEST"
  exit 1
fi

sleep 1
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 10 https://tei.dh.unibe.ch/outremer/ || echo 000)
echo "https://tei.dh.unibe.ch/outremer/ → HTTP $CODE"
[ "$CODE" = 200 ] || { echo "!! not serving yet — check: systemctl status outremer-web"; exit 1; }
echo "done"
