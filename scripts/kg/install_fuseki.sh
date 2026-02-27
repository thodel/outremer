#!/bin/bash
#
# install_fuseki.sh
# ─────────────────
# Install Apache Jena Fuseki triplestore on Ubuntu/Debian
#
# Usage:
#   sudo bash scripts/kg/install_fuseki.sh
#

set -e

echo "🔧 Installing Apache Jena Fuseki..."

# Configuration
FUSEKI_VERSION="4.10.0"
FUSEKI_USER="fuseki"
FUSEKI_HOME="/opt/fuseki"
FUSEKI_DATA="/var/lib/fuseki"
FUSEKI_PORT="3030"
SYSTEMD_SERVICE="/etc/systemd/system/fuseki.service"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root (sudo bash scripts/kg/install_fuseki.sh)"
    exit 1
fi

# Check if Java is installed
if ! command -v java &> /dev/null; then
    echo "⚠️  Java not found. Installing OpenJDK 17..."
    apt-get update
    apt-get install -y openjdk-17-jre-headless
fi

java_version=$(java -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)
if [ "$java_version" -lt 11 ]; then
    echo "❌ Java version must be 11 or higher (found: $java_version)"
    exit 1
fi

echo "✅ Java version: $(java -version 2>&1 | head -1)"

# Create Fuseki user
if ! id "$FUSEKI_USER" &>/dev/null; then
    echo "👤 Creating user: $FUSEKI_USER"
    useradd --system --no-create-home --shell /bin/false "$FUSEKI_USER"
fi

# Create directories
echo "📁 Creating directories..."
mkdir -p "$FUSEKI_HOME"
mkdir -p "$FUSEKI_DATA"
chown -R "$FUSEKI_USER:$FUSEKI_USER" "$FUSEKI_HOME"
chown -R "$FUSEKI_USER:$FUSEKI_USER" "$FUSEKI_DATA"

# Download Fuseki
echo "⬇️  Downloading Fuseki $FUSEKI_VERSION..."
cd /tmp
wget -q "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-${FUSEKI_VERSION}.tar.gz"

echo "📦 Extracting..."
tar -xzf "apache-jena-fuseki-${FUSEKI_VERSION}.tar.gz"
cp -r "apache-jena-fuseki-${FUSEKI_VERSION}"/* "$FUSEKI_HOME/"
rm -rf "apache-jena-fuseki-${FUSEKI_VERSION}"*

# Set permissions
chown -R "$FUSEKI_USER:$FUSEKI_USER" "$FUSEKI_HOME"
chmod +x "$FUSEKI_HOME/fuseki-server"

# Create systemd service
echo "📝 Creating systemd service..."
cat > "$SYSTEMD_SERVICE" << EOF
[Unit]
Description=Apache Jena Fuseki SPARQL Server
Documentation=https://jena.apache.org/documentation/fuseki2/
After=network.target

[Service]
Type=simple
User=$FUSEKI_USER
Group=$FUSEKI_USER
WorkingDirectory=$FUSEKI_HOME
Environment="FUSEKI_HOME=$FUSEKI_HOME"
Environment="FUSEKI_BASE=$FUSEKI_DATA"
ExecStart=$FUSEKI_HOME/fuseki-server --mem --update --port $FUSEKI_PORT /outremer
Restart=on-failure
RestartSec=10

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$FUSEKI_DATA

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
echo "🚀 Enabling and starting Fuseki service..."
systemctl daemon-reload
systemctl enable fuseki
systemctl start fuseki

# Wait for service to be ready
echo "⏳ Waiting for Fuseki to start..."
sleep 5

# Check status
if systemctl is-active --quiet fuseki; then
    echo "✅ Fuseki installed and running!"
    echo ""
    echo "📊 Access:"
    echo "   Web UI:    http://localhost:$FUSEKI_PORT"
    echo "   SPARQL:    http://localhost:$FUSEKI_PORT/outremer/query"
    echo "   Update:    http://localhost:$FUSEKI_PORT/outremer/update"
    echo ""
    echo "📝 Commands:"
    echo "   Status:    systemctl status fuseki"
    echo "   Stop:      systemctl stop fuseki"
    echo "   Restart:   systemctl restart fuseki"
    echo "   Logs:      journalctl -u fuseki -f"
    echo ""
    echo "📥 Load data:"
    echo "   cd /home/th/repos/outremer"
    echo "   .venv/bin/python3 scripts/kg/export_to_rdf.py"
    echo "   curl -X POST 'http://localhost:$FUSEKI_PORT/outremer/data' \\"
    echo "        -H 'Content-Type: text/turtle' \\"
    echo "        --data-binary @data/unified_kg.ttl"
else
    echo "❌ Fuseki failed to start. Check logs:"
    echo "   journalctl -u fuseki"
    exit 1
fi
