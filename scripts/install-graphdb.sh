#!/bin/bash
# install-graphdb.sh
# Install GraphDB Free Edition on Outremer VM
# Run this on the VM: ssh th@194.13.80.183 'bash -s' < install-graphdb.sh

set -e

echo "=== Installing GraphDB Free Edition ==="
echo ""

# Check if running on VM
if [ "$(hostname)" != "h1" ] && [ -z "$FORCE_INSTALL" ]; then
    echo "⚠️  Warning: This doesn't appear to be the Outremer VM (h1)"
    echo "   Set FORCE_INSTALL=1 to continue anyway"
    exit 1
fi

# 1. Download GraphDB
echo "📥 Downloading GraphDB Free 10.7.0..."
cd /opt
if [ -d "graphdb-free-10.7.0" ]; then
    echo "   ℹ️  GraphDB already downloaded, skipping..."
else
    sudo wget -q --show-progress http://graphdb.ontotext.com/download/graphdb-free-10.7.0.zip
    sudo unzip -q graphdb-free-10.7.0.zip
    sudo ln -sf graphdb-free-10.7.0 graphdb
    sudo chown -R th:th graphdb
    echo "   ✅ Download complete"
fi

# 2. Create systemd service
echo ""
echo "🔧 Creating systemd service..."
if [ -f "/etc/systemd/system/graphdb.service" ]; then
    echo "   ℹ️  Service already exists, skipping..."
else
    cat <<EOF | sudo tee /etc/systemd/system/graphdb.service > /dev/null
[Unit]
Description=GraphDB Triplestore
After=network.target

[Service]
Type=forking
User=th
ExecStart=/opt/graphdb/bin/graphdb start
ExecStop=/opt/graphdb/bin/graphdb stop
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    echo "   ✅ Service created"
fi

# 3. Enable and start GraphDB
echo ""
echo "🚀 Starting GraphDB..."
sudo systemctl enable graphdb
sudo systemctl start graphdb

# Wait for startup
sleep 5

# Check status
if sudo systemctl is-active --quiet graphdb; then
    echo "   ✅ GraphDB is running"
else
    echo "   ⚠️  GraphDB may still be starting..."
fi

# 4. Create data directories
echo ""
echo "📁 Creating data directories..."
mkdir -p ~/outremer-graph/{data,backup,ontologies,scripts}
echo "   ✅ Directories created in ~/outremer-graph/"

# 5. Download SDHSS ontology
echo ""
echo "📚 Downloading SDHSS ontology..."
cd ~/outremer-graph/ontologies
if [ -f "sdhss-core.ttl" ]; then
    echo "   ℹ️  SDHSS ontology already downloaded, skipping..."
else
    # Try Ontome first, fallback to GitHub
    if wget -q "https://ontome.net/ontology/export/11" -O sdhss-core.ttl; then
        echo "   ✅ SDHSS ontology downloaded from Ontome"
    else
        echo "   ⚠️  Ontome download failed, trying GitHub..."
        rm -f sdhss-core.ttl
        wget -q "https://raw.githubusercontent.com/sdhss/ontology/main/sdhss-core.ttl" -O sdhss-core.ttl || echo "   ❌ Could not download SDHSS ontology"
    fi
fi

# Download CIDOC CRM
if [ -f "cidoc-crm.owl" ]; then
    echo "   ℹ️  CIDOC CRM already downloaded, skipping..."
else
    wget -q "http://www.cidoc-crm.org/sites/default/files/cidoc_crm_v7.1.3.owl" -O cidoc-crm.owl && \
    echo "   ✅ CIDOC CRM downloaded" || \
    echo "   ⚠️  CIDOC CRM download failed (can be done manually)"
fi

# 6. Create conversion script
echo ""
echo "📝 Creating KG conversion script..."
cat <<'SCRIPT' > ~/outremer-graph/scripts/convert_kg_to_rdf.py
#!/usr/bin/env python3
"""Convert Outremer unified_kg.json to SDHSS-compatible RDF/Turtle"""

import json
import os
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD, OWL

CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
SDHSS = Namespace("https://sdhss.org/ontology/core/")
OUTREMER = Namespace("https://thodel.github.io/outremer/data/")

def convert_person(person_data):
    g = Graph()
    auth_id = person_data.get('identifiers', {}).get('outremer_auth')
    wikidata_id = person_data.get('identifiers', {}).get('wikidata_qid')
    
    if not auth_id and not wikidata_id:
        return g
    
    person_uri = OUTREMER[auth_id.replace(':', '_')] if auth_id else OUTREMER[f"WD_{wikidata_id}"]
    
    g.add((person_uri, RDF.type, CRM.E21_Person))
    g.add((person_uri, RDF.type, SDHSS.H1_Historical_Actor))
    
    name = person_data.get('names', {}).get('preferred_label', '')
    if name:
        g.add((person_uri, CRM.P1_is_identified_by, URIRef(f"{person_uri}_name")))
        g.add((URIRef(f"{person_uri}_name"), CRM.P190_has_symbolic_content, Literal(name)))
    
    if wikidata_id:
        g.add((person_uri, OWL.sameAs, URIRef(f"http://www.wikidata.org/entity/{wikidata_id}")))
    
    return g

def main():
    print("Loading Outremer KG...")
    kg_path = '/home/th/repos/outremer/data/unified_kg.json'
    if not os.path.exists(kg_path):
        print(f"❌ File not found: {kg_path}")
        return
    
    with open(kg_path) as f:
        kg = json.load(f)
    
    print(f"Converting {len(kg)} persons to RDF...")
    
    full_graph = Graph()
    full_graph.bind('crm', CRM)
    full_graph.bind('sdhss', SDHSS)
    full_graph.bind('outremer', OUTREMER)
    
    for i, (person_id, person_data) in enumerate(kg.items()):
        if i % 1000 == 0:
            print(f"  Processed {i}/{len(kg)} persons...")
        full_graph += convert_person(person_data)
    
    output_file = '/home/th/outremer-graph/data/outremer_sdhss.ttl'
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    print(f"Saving to {output_file}...")
    full_graph.serialize(destination=output_file, format='turtle')
    
    print(f"✅ Done! Generated {len(full_graph)} triples")
    if os.path.exists(output_file):
        size_mb = os.path.getsize(output_file) / 1024 / 1024
        print(f"   File size: {size_mb:.1f} MB")

if __name__ == "__main__":
    main()
SCRIPT

chmod +x ~/outremer-graph/scripts/convert_kg_to_rdf.py
echo "   ✅ Conversion script created"

# 7. Summary
echo ""
echo "========================================="
echo "✅ Installation Complete!"
echo "========================================="
echo ""
echo "📊 Status:"
echo "   GraphDB: $(sudo systemctl is-active graphdb)"
echo "   Access: http://$(hostname -I | awk '{print $1}'):7200"
echo "   Data dir: ~/outremer-graph/"
echo ""
echo "🔐 Default credentials:"
echo "   Username: admin"
echo "   Password: root (change this!)"
echo ""
echo "📚 Next steps:"
echo "   1. Visit http://$(hostname -I | awk '{print $1}'):7200"
echo "   2. Create repository 'outremer'"
echo "   3. Upload ontologies from ~/outremer-graph/ontologies/"
echo "   4. Run conversion: cd ~/outremer-graph/scripts && python3 convert_kg_to_rdf.py"
echo "   5. Load data into GraphDB"
echo ""
echo "📖 Full guide: ~/repos/outremer/docs/SDHSS_QUICKSTART.md"
echo ""
