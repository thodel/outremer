#!/bin/bash
# install-graphdb-alt.sh
# Tries multiple download sources

set -e

echo "=== GraphDB Installation (Multi-Source) ==="
echo ""

cd /opt

# Check if already installed
if [ -d "graphdb-free-10.7.0" ]; then
    echo "✅ GraphDB already installed!"
    cd /opt/graphdb/bin && ./graphdb start
    exit 0
fi

sudo rm -f graphdb-free-*.zip

# Try multiple sources
SOURCES=(
    "http://graphdb.ontotext.com/download/graphdb-free-10.7.0.zip"
    "https://github.com/ontotext/GraphDB/releases/download/10.7.0/graphdb-free-10.7.0-linux-x64.zip"
    "https://repo1.maven.org/maven2/com/ontograph/graphdb-free/10.7.0/graphdb-free-10.7.0-linux-x64.zip"
)

DOWNLOAD_OK=false

for i in "${!SOURCES[@]}"; do
    SOURCE="${SOURCES[$i]}"
    echo "📥 Attempt $((i+1))/${#SOURCES[@]}: $SOURCE"
    
    if command -v curl &> /dev/null; then
        sudo curl -L -f -o graphdb-free-10.7.0.zip "$SOURCE" --progress-bar 2>&1 || true
    else
        sudo wget -q --show-progress "$SOURCE" -O graphdb-free-10.7.0.zip 2>&1 || true
    fi
    
    if [ -f "graphdb-free-10.7.0.zip" ]; then
        FILE_SIZE=$(stat -c%s "graphdb-free-10.7.0.zip")
        if [ $FILE_SIZE -gt 100000000 ]; then  # > 100MB
            echo "✅ Download successful ($((FILE_SIZE / 1024 / 1024)) MB)"
            DOWNLOAD_OK=true
            break
        else
            echo "⚠️  File too small, trying next source..."
            sudo rm -f graphdb-free-10.7.0.zip
        fi
    fi
    echo ""
done

if [ "$DOWNLOAD_OK" = false ]; then
    echo "❌ All download sources failed!"
    echo ""
    echo "═══════════════════════════════════════"
    echo "MANUAL DOWNLOAD REQUIRED"
    echo "═══════════════════════════════════════"
    echo ""
    echo "Option A: Official Website"
    echo "  1. Visit: https://www.ontotext.com/products/graphdb/download/"
    echo "  2. Register (free, required for download)"
    echo "  3. Download 'GraphDB Free 10.7.0 for Linux'"
    echo "  4. Upload to VM:"
    echo "     scp ~/Downloads/graphdb-free-10.7.0.zip th@194.13.80.183:/opt/"
    echo ""
    echo "Option B: Use Apache Jena Fuseki (Alternative)"
    echo "  Run: bash /home/th/repos/outremer/scripts/install-fuseki.sh"
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
echo "✅ GraphDB installed!"
echo ""
echo "Start: cd /opt/graphdb/bin && ./graphdb start"
echo "Access: http://194.13.80.183:7200"
