#!/bin/bash
# install-graphdb-simple.sh
# Simplified GraphDB installation - no systemd required

set -e

echo "=== Installing GraphDB Free (Simple Mode) ==="
echo ""

# 1. Download GraphDB
echo "📥 Step 1/5: Downloading GraphDB..."
cd /opt
if [ -d "graphdb-free-10.7.0" ]; then
    echo "   ℹ️  GraphDB already exists, skipping download"
else
    echo "   Downloading (~300 MB, this may take 1-2 minutes)..."
    sudo wget -q --show-progress http://graphdb.ontotext.com/download/graphdb-free-10.7.0.zip
    echo "   Extracting..."
    sudo unzip -q graphdb-free-10.7.0.zip
    sudo ln -sf graphdb-free-10.7.0 graphdb
    sudo chown -R th:th graphdb
    echo "   ✅ Download complete"
fi

# 2. Create directories
echo ""
echo "📁 Step 2/5: Creating directories..."
mkdir -p ~/outremer-graph/{data,backup,ontologies,scripts}
echo "   ✅ Created ~/outremer-graph/"

# 3. Download ontologies
echo ""
echo "📚 Step 3/5: Downloading ontologies..."
cd ~/outremer-graph/ontologies

if [ ! -f "sdhss-core.ttl" ]; then
    echo "   Downloading SDHSS ontology..."
    wget -q "https://ontome.net/ontology/export/11" -O sdhss-core.ttl || \
    wget -q "https://raw.githubusercontent.com/sdhss/ontology/main/sdhss-core.ttl" -O sdhss-core.ttl || \
    echo "   ⚠️  Could not download SDHSS (manual download needed)"
else
    echo "   ℹ️  SDHSS ontology already exists"
fi

if [ ! -f "cidoc-crm.owl" ]; then
    echo "   Downloading CIDOC CRM..."
    wget -q "http://www.cidoc-crm.org/sites/default/files/cidoc_crm_v7.1.3.owl" -O cidoc-crm.owl || \
    echo "   ⚠️  Could not download CIDOC CRM (manual download needed)"
else
    echo "   ℹ️  CIDOC CRM already exists"
fi

ls -lh *.ttl *.owl 2>/dev/null || echo "   ⚠️  No ontology files found"
echo "   ✅ Ontologies ready"

# 4. Create conversion script
echo ""
echo "📝 Step 4/5: Creating conversion script..."
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
        print("   Run this from the VM: ssh th@194.13.80.183")
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

# 5. Install rdflib if needed
echo ""
echo "🔧 Step 5/5: Checking Python dependencies..."
if python3 -c "import rdflib" 2>/dev/null; then
    echo "   ℹ️  rdflib already installed"
else
    echo "   Installing rdflib..."
    pip3 install --user rdflib || {
        echo "   ⚠️  pip3 install failed. Try:"
        echo "      source ~/repos/outremer/.venv/bin/activate"
        echo "      pip install rdflib"
    }
fi
echo "   ✅ Dependencies ready"

# Summary
echo ""
echo "========================================="
echo "✅ Installation Complete!"
echo "========================================="
echo ""
echo "📊 What's ready:"
echo "   ✓ GraphDB: /opt/graphdb/"
echo "   ✓ Data dir: ~/outremer-graph/"
echo "   ✓ Ontologies: ~/outremer-graph/ontologies/"
echo "   ✓ Conversion script: ~/outremer-graph/scripts/convert_kg_to_rdf.py"
echo ""
echo "🚀 Next steps:"
echo ""
echo "   1. Start GraphDB manually:"
echo "      cd /opt/graphdb/bin"
echo "      ./graphdb start"
echo ""
echo "   2. Open browser: http://194.13.80.183:7200"
echo "      Login: admin / root"
echo ""
echo "   3. Create repository 'outremer' (Free SES File)"
echo ""
echo "   4. Upload ontologies from ~/outremer-graph/ontologies/"
echo ""
echo "   5. Convert KG to RDF:"
echo "      cd ~/outremer-graph/scripts"
echo "      python3 convert_kg_to_rdf.py"
echo ""
echo "   6. Load outremer_sdhss.ttl into GraphDB"
echo ""
echo "📖 Full guide: ~/repos/outremer/docs/SDHSS_QUICKSTART.md"
echo ""
echo "💡 Tip: To stop GraphDB later:"
echo "      cd /opt/graphdb/bin"
echo "      ./graphdb stop"
echo ""
