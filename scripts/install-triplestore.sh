#!/bin/bash
# install-triplestore.sh — Canonical triplestore installation for OUTREMER
#
# Choose between:
#   1. Apache Jena Fuseki  — open-source, lightweight (~60 MB), no registration
#   2. GraphDB Free        — requires free registration, ~300 MB
#
# Usage:
#   bash scripts/install-triplestore.sh [fuseki|graphdb]
#   bash scripts/install-triplestore.sh  # interactive

set -e

CHOICE="${1:-}"

if [ -z "$CHOICE" ]; then
    echo "=== OUTREMER Triplestore Installation ==="
    echo ""
    echo "Choose a triplestore to install:"
    echo ""
    echo "  [1] Fuseki  — Apache Jena Fuseki 4.10.0"
    echo "           Open-source (Apache License 2.0)"
    echo "           Lightweight (~60 MB download)"
    echo "           No registration required"
    echo "           Recommended for OUTREMER"
    echo ""
    echo "  [2] GraphDB — Ontotext GraphDB Free 10.7.0"
    echo "           Free registration required at ontotext.com"
    echo "           Heavier (~300 MB download)"
    echo ""
    echo -n "Select [1/2] (default: 1): "
    read -r CHOICE
fi

case "$CHOICE" in
    2|graphdb|GraphDB)
        INSTALL_GRAPHDB=1
        ;;
    *)
        INSTALL_GRAPHDB=0
        ;;
esac

cd /opt

if [ "$INSTALL_GRAPHDB" = "1" ]; then
    echo ""
    echo "=== Installing GraphDB Free 10.7.0 ==="
    echo ""

    # Check if already installed
    if [ -d "graphdb-free-10.7.0" ]; then
        echo "✅ GraphDB already installed at /opt/graphdb-free-10.7.0"
        ls -lh graphdb-free-10.7.0/
        echo ""
        echo "🚀 Start: cd /opt/graphdb/bin && ./graphdb start"
        echo "🌐 Access: http://$(hostname -I | awk '{print $1}'):7200"
        exit 0
    fi

    echo "⚠️  GraphDB requires free registration at ontotext.com"
    echo ""
    echo "📋 Manual steps:"
    echo "  1. Visit: https://www.ontotext.com/products/graphdb/download/"
    echo "  2. Click 'Download GraphDB Free' (register if needed)"
    echo "  3. Download 'GraphDB Free 10.7.0 for Linux'"
    echo "  4. Upload to VM: scp ~/Downloads/graphdb-free-10.7.0.zip /opt/"
    echo "  5. Extract: cd /opt && sudo unzip graphdb-free-10.7.0.zip"
    echo "  6. Symlink: sudo ln -s graphdb-free-10.7.0 graphdb"
    echo "  7. Start: cd /opt/graphdb/bin && ./graphdb start"
    echo ""
    echo "OR use Fuseki instead (option 1, no registration needed):"
    echo "  bash scripts/install-triplestore.sh fuseki"
    echo ""
    exit 1

else
    echo ""
    echo "=== Installing Apache Jena Fuseki 4.10.0 ==="
    echo ""

    if [ -d "apache-jena-fuseki-4.10.0" ]; then
        echo "✅ Fuseki already installed at /opt/apache-jena-fuseki-4.10.0"
        ls -lh apache-jena-fuseki-4.10.0/
        echo ""
        echo "🚀 Start: ~/fuseki-start.sh"
        exit 0
    fi

    echo "📥 Downloading Apache Jena Fuseki 4.10.0 (~60 MB)..."
    sudo wget -q --show-progress \
        "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-4.10.0.tar.gz" \
        -O apache-jena-fuseki-4.10.0.tar.gz

    echo ""
    echo "📦 Extracting..."
    sudo tar xzf apache-jena-fuseki-4.10.0.tar.gz
    sudo ln -sf apache-jena-fuseki-4.10.0 fuseki
    sudo chown -R "$USER:$USER" fuseki
    echo "✅ Extraction complete"

    echo ""
    echo "📁 Creating data directory..."
    mkdir -p ~/fuseki-data
    echo ""

    echo "========================================="
    echo "✅ Fuseki Installed!"
    echo "========================================="
    echo ""
    echo "🚀 Quick start:"
    echo "   cd /opt/fuseki"
    echo "   ./bin/fuseki-server --tdb2 --loc=\$HOME/fuseki-data /outremer"
    echo ""
    echo "   Or use the convenience script:"
    echo "   ~/fuseki-start.sh"
    echo ""
    echo "🌐 Access: http://localhost:3030"
    echo ""
fi