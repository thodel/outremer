#!/bin/bash
# install-graphdb-fixed.sh
# Fixed version with proper redirect handling

set -e

echo "=== GraphDB Installation (Fixed) ==="
echo ""

cd /opt

# Check if already installed
if [ -d "graphdb-free-10.7.0" ]; then
    echo "✅ GraphDB already installed!"
    ls -lh graphdb-free-10.7.0/
    echo ""
    echo "Start with: cd /opt/graphdb/bin && ./graphdb start"
    exit 0
fi

echo "📥 Downloading GraphDB Free 10.7.0..."
echo ""

# Remove any failed downloads
sudo rm -f graphdb-free-10.7.0.zip

# Try with curl (better redirect handling)
if command -v curl &> /dev/null; then
    echo "Using curl (better for redirects)..."
    sudo curl -L -o graphdb-free-10.7.0.zip \
        "http://graphdb.ontotext.com/download/graphdb-free-10.7.0.zip" \
        --progress-bar
else
    echo "Using wget with redirect follow..."
    sudo wget --max-redirect=5 \
        http://graphdb.ontotext.com/download/graphdb-free-10.7.0.zip \
        -O graphdb-free-10.7.0.zip
fi

echo ""

# Check if download succeeded
if [ ! -f "graphdb-free-10.7.0.zip" ]; then
    echo "❌ Download failed - file not found"
    exit 1
fi

FILE_SIZE=$(stat -c%s "graphdb-free-10.7.0.zip")
echo "📊 Downloaded file size: $((FILE_SIZE / 1024 / 1024)) MB"

if [ $FILE_SIZE -lt 1000000 ]; then
    echo "❌ File too small (< 1MB) - download failed"
    echo ""
    echo "Contents of downloaded file:"
    head -20 graphdb-free-10.7.0.zip || true
    echo ""
    echo "Manual download required:"
    echo "  1. Visit: https://www.ontotext.com/products/graphdb/download/"
    echo "  2. Register/login (free)"
    echo "  3. Download GraphDB Free 10.7.0 for Linux"
    echo "  4. Upload: scp ~/Downloads/graphdb-free-10.7.0.zip th@194.13.80.183:/opt/"
    echo "  5. Run: cd /opt && sudo unzip graphdb-free-10.7.0.zip"
    exit 1
fi

echo "✅ Download successful!"
echo ""
echo "📦 Extracting..."
sudo unzip -q graphdb-free-10.7.0.zip
sudo ln -sf graphdb-free-10.7.0 graphdb
sudo chown -R th:th graphdb
echo "✅ Extraction complete"

echo ""
echo "📁 Installation verified:"
ls -lh /opt/graphdb/

echo ""
echo "========================================="
echo "✅ GraphDB Ready!"
echo "========================================="
echo ""
echo "🚀 Start GraphDB:"
echo "  cd /opt/graphdb/bin"
echo "  ./graphdb start"
echo ""
echo "🌐 Access: http://194.13.80.183:7200"
echo "🔐 Login: admin / root"
echo ""
