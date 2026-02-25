#!/bin/bash
# install-graphdb-manual.sh
# Step-by-step installation with verbose output

set -e

echo "=== GraphDB Manual Installation ==="
echo ""

# Step 1: Check disk space
echo "📊 Checking disk space..."
df -h /opt
echo ""

# Step 2: Download GraphDB
echo "📥 Downloading GraphDB Free 10.7.0..."
cd /opt

if [ -d "graphdb-free-10.7.0" ]; then
    echo "✅ GraphDB already downloaded"
    ls -lh graphdb-free-10.7.0/
else
    echo "Downloading zip file (~300 MB)..."
    
    # Try direct download with verbose output
    echo "Starting download (this may take 1-2 minutes)..."
    sudo wget --progress=bar:force http://graphdb.ontotext.com/download/graphdb-free-10.7.0.zip -O graphdb-free-10.7.0.zip
    
    DOWNLOAD_STATUS=$?
    
    if [ $DOWNLOAD_STATUS -eq 0 ] && [ -f "graphdb-free-10.7.0.zip" ]; then
        echo ""
        echo "✅ Download complete!"
        ls -lh graphdb-free-10.7.0.zip
        
        echo ""
        echo "📦 Extracting..."
        sudo unzip -q graphdb-free-10.7.0.zip
        sudo ln -sf graphdb-free-10.7.0 graphdb
        sudo chown -R th:th graphdb
        echo "✅ Extraction complete"
    else
        echo ""
        echo "❌ Download failed (exit code: $DOWNLOAD_STATUS)"
        echo ""
        echo "Check log: /tmp/graphdb-download.log"
        echo "Or see error above."
        echo ""
        echo "Alternative: Download manually from browser:"
        echo "  1. Visit: http://graphdb.ontotext.com/download/free/"
        echo "  2. Download 'GraphDB Free 10.7.0 for Linux'"
        echo "  3. Upload to VM: scp graphdb-free-10.7.0.zip th@194.13.80.183:/opt/"
        echo "  4. Then run: cd /opt && sudo unzip graphdb-free-10.7.0.zip"
        exit 1
    fi
fi

echo ""
echo "📁 Verifying installation..."
if [ -d "/opt/graphdb" ]; then
    ls -lh /opt/graphdb/
    echo ""
    echo "✅ GraphDB installed successfully!"
    echo ""
    echo "🚀 Next steps:"
    echo "  cd /opt/graphdb/bin"
    echo "  ./graphdb start"
    echo ""
    echo "Then open: http://194.13.80.183:7200"
    echo "Login: admin / root"
else
    echo "❌ Installation directory not found!"
    exit 1
fi
