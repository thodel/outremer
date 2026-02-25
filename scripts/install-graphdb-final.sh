#!/bin/bash
# install-graphdb-final.sh
# Updated with correct GraphDB download URLs

set -e

echo "=== GraphDB Installation (Updated URLs) ==="
echo ""

cd /opt

# Check if already installed
if [ -d "graphdb-free-10.7.0" ]; then
    echo "✅ GraphDB already installed!"
    ls -lh graphdb-free-10.7.0/
    exit 0
fi

sudo rm -f graphdb-free-*.zip

echo "📥 Downloading GraphDB Free 10.7.0..."
echo ""

# Try the new official download page URL
URLS=(
    "https://www.ontotext.com/products/graphdb/download/"
    "https://github.com/OntoText/GraphDB-Examples/releases/download/v10.7.0/graphdb-free-10.7.0-linux-x64.zip"
)

DOWNLOAD_OK=false

for URL in "${URLS[@]}"; do
    echo "Trying: $URL"
    
    if command -v curl &> /dev/null; then
        sudo curl -L -f -o graphdb-free-10.7.0.zip "$URL" --progress-bar 2>&1 || true
    else
        sudo wget --max-redirect=5 -q --show-progress "$URL" -O graphdb-free-10.7.0.zip 2>&1 || true
    fi
    
    if [ -f "graphdb-free-10.7.0.zip" ]; then
        FILE_SIZE=$(stat -c%s "graphdb-free-10.7.0.zip")
        if [ $FILE_SIZE -gt 100000000 ]; then
            echo "✅ Download successful ($((FILE_SIZE / 1024 / 1024)) MB)"
            DOWNLOAD_OK=true
            break
        else
            echo "⚠️  File too small, trying next URL..."
            sudo rm -f graphdb-free-10.7.0.zip
        fi
    fi
    echo ""
done

if [ "$DOWNLOAD_OK" = false ]; then
    echo "═══════════════════════════════════════"
    echo "AUTOMATED DOWNLOAD NOT AVAILABLE"
    echo "═══════════════════════════════════════"
    echo ""
    echo "GraphDB now requires registration for download."
    echo ""
    echo "📋 MANUAL DOWNLOAD STEPS:"
    echo ""
    echo "1. Visit in your browser:"
    echo "   https://www.ontotext.com/products/graphdb/download/"
    echo ""
    echo "2. Click 'Download GraphDB Free'"
    echo "   (You'll need to register - free, takes 2 min)"
    echo ""
    echo "3. Download: 'GraphDB Free 10.7.0 for Linux'"
    echo ""
    echo "4. Upload to VM:"
    echo "   scp ~/Downloads/graphdb-free-10.7.0.zip th@194.13.80.183:/opt/"
    echo ""
    echo "5. Extract on VM:"
    echo "   cd /opt"
    echo "   sudo unzip graphdb-free-10.7.0.zip"
    echo "   sudo ln -s graphdb-free-10.7.0 graphdb"
    echo "   cd /opt/graphdb/bin"
    echo "   ./graphdb start"
    echo ""
    echo "═══════════════════════════════════════"
    echo "OR USE FUSEKI (NO REGISTRATION)"
    echo "═══════════════════════════════════════"
    echo ""
    echo "Run this instead:"
    echo "  bash /home/th/repos/outremer/scripts/install-fuseki.sh"
    echo ""
    echo "Fuseki is open-source, lighter (60MB), no registration."
    echo "Works great for Outremer's needs."
    echo ""
    exit 1
fi

echo ""
echo "📦 Extracting..."
sudo unzip -q graphdb-free-10.7.0.zip
sudo ln -sf graphdb-free-10.7.0 graphdb
sudo chown -R th:th graphdb
echo "✅ Extraction complete"

echo ""
ls -lh /opt/graphdb/

echo ""
echo "========================================="
echo "✅ GraphDB Installed!"
echo "========================================="
echo ""
echo "🚀 Start: cd /opt/graphdb/bin && ./graphdb start"
echo "🌐 Access: http://194.13.80.183:7200"
echo "🔐 Login: admin / root"
echo ""
