# SDHSS Migration - Quick Start Guide

**TL;DR:** Get SDHSS-based knowledge graph running on your VM in 30 minutes.

---

## Step 1: Install GraphDB (5 minutes)

SSH into your VM:
```bash
ssh th@194.13.80.183
```

Download and install GraphDB Free:
```bash
cd /opt
sudo wget http://graphdb.ontotext.com/download/graphdb-free-10.7.0.zip
sudo unzip graphdb-free-10.7.0.zip
sudo ln -s graphdb-free-10.7.0 graphdb
sudo chown -R th:th graphdb
```

Create systemd service:
```bash
cat <<EOF | sudo tee /etc/systemd/system/graphdb.service
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
sudo systemctl enable graphdb
sudo systemctl start graphdb
sudo systemctl status graphdb  # Should show "active (running)"
```

---

## Step 2: Verify Installation (2 minutes)

Open browser: http://194.13.80.183:7200

You should see the GraphDB Workbench login screen.

**Default credentials:**
- Username: `admin`
- Password: `root` (change this!)

---

## Step 3: Download SDHSS Ontology (3 minutes)

```bash
mkdir -p ~/outremer-graph/{data,backup,ontologies}
cd ~/outremer-graph/ontologies

# Download SDHSS Core ontology from Ontome
wget "https://ontome.net/ontology/export/11" -O sdhss-core.ttl

# Also download CIDOC CRM base (required dependency)
wget "http://www.cidoc-crm.org/sites/default/files/cidoc_crm_v7.1.3.owl" -O cidoc-crm.owl
```

Verify files downloaded:
```bash
ls -lh *.ttl *.owl
# Should show:
# cidoc-crm.owl (~200 KB)
# sdhss-core.ttl (~150 KB)
```

---

## Step 4: Create Repository (5 minutes)

In GraphDB Workbench (http://194.13.80.183:7200):

1. Click **"Repositories"** → **"Create repository"**
2. Choose **"Free SES Memory"** (for testing) or **"Free SES File"** (for persistence)
3. Repository ID: `outremer`
4. Click **"Create"**

---

## Step 5: Upload Ontologies (5 minutes)

1. Select repository: `outremer`
2. Click **"Import"** → **"Upload RDF files..."**
3. Upload `cidoc-crm.owl` first
4. Upload `sdhss-core.ttl` second
5. Wait for import to complete

Verify ontologies loaded:
```sparql
SELECT ?class (COUNT(?class) AS ?count)
WHERE {
  ?class a owl:Class .
}
GROUP BY ?class
```

Should return ~100+ classes (CIDOC CRM + SDHSS).

---

## Step 6: Convert Outremer KG to RDF (10 minutes)

Create conversion script:
```bash
cd ~/outremer-graph/scripts
nano convert_kg_to_rdf.py
```

Paste this code:

```python
#!/usr/bin/env python3
"""
Convert Outremer unified_kg.json to SDHSS-compatible RDF/Turtle
"""

import json
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD, OWL

# Namespaces
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
SDHSS = Namespace("https://sdhss.org/ontology/core/")
OUTREMER = Namespace("https://thodel.github.io/outremer/data/")

def convert_person(person_data):
    """Convert a single person to RDF triples."""
    g = Graph()
    
    # Get person ID
    auth_id = person_data.get('identifiers', {}).get('outremer_auth')
    wikidata_id = person_data.get('identifiers', {}).get('wikidata_qid')
    
    if not auth_id and not wikidata_id:
        return g
    
    # Create URI
    person_uri = OUTREMER[auth_id.replace(':', '_')] if auth_id else OUTREMER[wikidata_id]
    
    # Add type
    g.add((person_uri, RDF.type, CRM.E21_Person))
    g.add((person_uri, RDF.type, SDHSS.H1_Historical_Actor))
    
    # Add name
    name = person_data.get('names', {}).get('preferred_label', '')
    if name:
        g.add((person_uri, CRM.P1_is_identified_by, 
               URIRef(f"{person_uri}_name")))
        g.add((URIRef(f"{person_uri}_name"), CRM.P190_has_symbolic_content, 
               Literal(name)))
    
    # Add Wikidata link
    if wikidata_id:
        g.add((person_uri, OWL.sameAs, 
               URIRef(f"http://www.wikidata.org/entity/{wikidata_id}")))
    
    # Add birth/death dates (if available)
    dates = person_data.get('dates', {})
    if dates.get('birth'):
        birth_uri = URIRef(f"{person_uri}_birth")
        g.add((person_uri, CRM.P98i_was_born, birth_uri))
        g.add((birth_uri, RDF.type, CRM.E67_Birth))
        g.add((birth_uri, CRM.P4_has_time-span,
               Literal(dates['birth'], datatype=XSD.gYear)))
    
    if dates.get('death'):
        death_uri = URIRef(f"{person_uri}_death")
        g.add((person_uri, CRM.P99i_died, death_uri))
        g.add((death_uri, RDF.type, CRM.E69_Death))
        g.add((death_uri, CRM.P4_has_time-span,
               Literal(dates['death'], datatype=XSD.gYear)))
    
    return g

def main():
    print("Loading Outremer KG...")
    with open('/home/th/repos/outremer/data/unified_kg.json') as f:
        kg = json.load(f)
    
    print(f"Converting {len(kg)} persons to RDF...")
    
    full_graph = Graph()
    full_graph.bind('crm', CRM)
    full_graph.bind('sdhss', SDHSS)
    full_graph.bind('outremer', OUTREMER)
    
    for i, (person_id, person_data) in enumerate(kg.items()):
        if i % 1000 == 0:
            print(f"  Processed {i}/{len(kg)} persons...")
        
        person_graph = convert_person(person_data)
        full_graph += person_graph
    
    # Save output
    output_file = '/home/th/outremer-graph/data/outremer_sdhss.ttl'
    print(f"Saving to {output_file}...")
    full_graph.serialize(destination=output_file, format='turtle')
    
    print(f"✅ Done! Generated {len(full_graph)} triples")
    print(f"   File size: {os.path.getsize(output_file) / 1024 / 1024:.1f} MB")

if __name__ == "__main__":
    import os
    main()
```

Run conversion:
```bash
cd ~/outremer-graph/scripts
python3 convert_kg_to_rdf.py
```

Expected output:
```
Loading Outremer KG...
Converting 19085 persons to RDF...
  Processed 0/19085 persons...
  Processed 1000/19085 persons...
  ...
✅ Done! Generated ~950,000 triples
   File size: 45.2 MB
```

---

## Step 7: Load Data into GraphDB (5 minutes)

In GraphDB Workbench:

1. Select repository: `outremer`
2. Click **"Import"** → **"Upload RDF files..."**
3. Upload `/home/th/outremer-graph/data/outremer_sdhss.ttl`
4. Wait for import (may take 2-3 minutes for 1M triples)

Verify data loaded:
```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX outremer: <https://thodel.github.io/outremer/data/>

SELECT (COUNT(?person) AS ?total)
WHERE {
  ?person a crm:E21_Person .
}
```

Should return: **~19,000** (or however many persons converted)

---

## Step 8: Test SPARQL Endpoint (2 minutes)

Try this query in GraphDB's **"SPARQL & SPARQL Update"** tab:

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX outremer: <https://thodel.github.io/outremer/data/>

SELECT ?person ?name
WHERE {
  ?person a crm:E21_Person ;
          crm:P1_is_identified_by/crm:P190_has_symbolic_content ?name .
  
  FILTER(CONTAINS(LCASE(?name), "baldwin"))
}
LIMIT 10
```

Should return all persons named "Baldwin" in your KG.

---

## ✅ You're Done!

Your SDHSS-based knowledge graph is now running!

### What's Next?

1. **Configure Caddy reverse proxy** (for HTTPS access)
2. **Set up SHACL validation** (ensure data quality)
3. **Build reconciliation UI** (see RECONCILIATION_INTERFACE_PROPOSAL.md)
4. **Write example queries** (for documentation)

### Access Points

- **GraphDB Workbench:** http://194.13.80.183:7200
- **SPARQL endpoint:** http://194.13.80.183:7200/repositories/outremer
- **Data file:** ~/outremer-graph/data/outremer_sdhss.ttl

---

## Troubleshooting

### GraphDB won't start
```bash
sudo journalctl -u graphdb -n 50  # Check logs
sudo systemctl restart graphdb
```

### Out of memory
Edit `/opt/graphdb/conf/graphdb.properties`:
```properties
-Xmx=2g  # Reduce from default 4g if needed
```

### Ontology download fails
Try alternative source:
```bash
wget "https://raw.githubusercontent.com/sdhss/ontology/main/sdhss-core.ttl" -O sdhss-core.ttl
```

### Conversion script errors
Install rdflib:
```bash
source ~/.openclaw/workspace/../venv/bin/activate  # Or use system Python
pip3 install rdflib
```

---

**Questions?** See full proposal: `docs/RECONCILIATION_INTERFACE_PROPOSAL.md`

🏰✨
