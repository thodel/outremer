#!/bin/bash
# install-fuseki.sh
# Install Apache Jena Fuseki (open source alternative to GraphDB)

set -e

echo "=== Installing Apache Jena Fuseki ==="
echo ""
echo "ℹ️  Fuseki is a fully open-source SPARQL server (Apache License)"
echo "   Lighter than GraphDB, no registration required"
echo ""

cd /opt

# Check if already installed
if [ -d "apache-jena-fuseki-4.10.0" ]; then
    echo "✅ Fuseki already installed!"
    ls -lh apache-jena-fuseki-4.10.0/
    exit 0
fi

echo "📥 Downloading Apache Jena Fuseki 4.10.0..."
echo "   (~60 MB, faster than GraphDB's 300 MB)"

# Direct Apache mirror download (no registration needed)
sudo wget -q --show-progress \
    "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-4.10.0.tar.gz" \
    -O apache-jena-fuseki-4.10.0.tar.gz

echo ""
echo "📦 Extracting..."
sudo tar xzf apache-jena-fuseki-4.10.0.tar.gz
sudo ln -sf apache-jena-fuseki-4.10.0 fuseki
sudo chown -R th:th fuseki
echo "✅ Extraction complete"

echo ""
echo "📁 Creating data directory..."
mkdir -p ~/fuseki-data
chown th:th ~/fuseki-data

echo ""
echo "📝 Creating startup script..."
cat <<'STARTSCRIPT' > ~/start-fuseki.sh
#!/bin/bash
cd /opt/fuseki
export FUSEKI_HOME=/opt/fuseki
export FUSEKI_BASE=$HOME/fuseki-data
./fuseki-server --mem --port 3030 /outremer
STARTSCRIPT

chmod +x ~/start-fuseki.sh

echo ""
echo "========================================="
echo "✅ Fuseki Ready!"
echo "========================================="
echo ""
echo "🚀 Start Fuseki:"
echo "  ~/start-fuseki.sh"
echo "  (or manually: cd /opt/fuseki && ./fuseki-server --mem --port 3030 /outremer)"
echo ""
echo "🌐 Access: http://194.13.80.183:3030"
echo ""
echo "📊 Interface features:"
echo "  - SPARQL query editor"
echo "  - Data upload (RDF/XML, Turtle, N-Triples)"
echo "  - Dataset management"
echo "  - REST API"
echo ""
echo "🔄 Next steps after starting:"
echo "  1. Open http://194.13.80.183:3030"
echo "  2. Click on 'outremer' dataset"
echo "  3. Go to 'Upload' tab"
echo "  4. Upload ontologies and KG data"
echo ""
echo "💡 To run in background (Ctrl+Z won't stop it):"
echo "  nohup ~/start-fuseki.sh > ~/fuseki.log 2>&1 &"
echo ""
