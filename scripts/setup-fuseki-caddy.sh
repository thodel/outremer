#!/bin/bash
# setup-fuseki-caddy.sh
# Add Fuseki reverse proxy to Caddy

set -e

echo "=== Adding Fuseki to Caddy ==="
echo ""

# Backup current Caddyfile
echo "📦 Backing up current Caddyfile..."
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.backup.$(date +%Y%m%d-%H%M%S)
echo "✅ Backup created"

# Add Fuseki reverse proxy
echo ""
echo "📝 Updating Caddyfile..."
sudo cat >> /etc/caddy/Caddyfile <<'CADDY'

# Apache Jena Fuseki (SPARQL endpoint)
fuseki.hodelweb.ch {
    reverse_proxy localhost:3030
    encode gzip
}
CADDY

echo "✅ Caddyfile updated"

# Show updated config
echo ""
echo "📋 New Caddyfile:"
sudo cat /etc/caddy/Caddyfile

# Reload Caddy
echo ""
echo "🔄 Reloading Caddy..."
sudo systemctl reload caddy

# Check status
echo ""
echo "✅ Caddy reloaded successfully!"
echo ""
echo "🌐 Access Fuseki at:"
echo "   https://fuseki.hodelweb.ch"
echo ""
echo "💡 Note: DNS must point fuseki.hodelweb.ch to 194.13.80.183"
echo "   If not set yet, add in Netcup DNS panel:"
echo "   fuseki.hodelweb.ch.  IN  A  194.13.80.183"
echo ""
