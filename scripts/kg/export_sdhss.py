#!/usr/bin/env python3
"""
export_sdhss.py  –  Outremer → SDHSS/CIDOC-CRM RDF/Turtle
"""
import json, re, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT   = Path(__file__).resolve().parents[2]
INPUT  = ROOT / "data" / "unified_kg.json"
OUTPUT = ROOT / "data" / "unified_kg_sdhss.ttl"

PREFIXES = """\
@prefix rdf:      <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:      <http://www.w3.org/2002/07/owl#> .
@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .
@prefix skos:     <http://www.w3.org/2004/02/skos/core#> .
@prefix crm:      <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix sdhss:    <https://sdhss.org/ontology/core/1.2/> .
@prefix outremer: <http://outremer.hodelweb.ch/entity/> .
@prefix wd:       <http://www.wikidata.org/entity/> .
"""

GENDER_URI = {"m": "outremer:Gender_Male", "f": "outremer:Gender_Female"}

def uri(eid):
    if eid.startswith("WIKIDATA:"): return f"wd:{eid[9:]}"
    return f"outremer:{re.sub(r'[^A-Za-z0-9_]', '_', eid)}"

def lid(eid):
    return re.sub(r'[^A-Za-z0-9_]', '_', eid)

def esc(s):
    return str(s).replace("\\","\\\\").replace('"','\\"').replace("\n","\\n")

def year(d):
    if not d: return None
    m = re.search(r'\b(-?\d{3,4})\b', str(d))
    return f'"{m.group(1)}"^^xsd:gYear' if m else None

def triples(subj, po_list, out):
    """Write subject + list of (pred, obj) as Turtle."""
    pos = [(p,o) for p,o in po_list if o is not None]
    if not pos: return
    out.write(f"{subj}\n")
    for i,(p,o) in enumerate(pos):
        sep = " ;\n" if i < len(pos)-1 else " .\n"
        out.write(f"  {p} {o}{sep}")
    out.write("\n")

def emit_person(pid, p, out):
    u     = uri(pid)
    label = p.get("preferred_label","")
    names = p.get("names",{}) or {}
    bio   = p.get("bio",{}) or {}
    rels  = p.get("relationships",[]) or []
    idents= p.get("identifiers",{}) or {}
    prov  = p.get("provenance",{}) or {}
    lp    = lid(pid)

    birth = bio.get("birth") or {}
    death = bio.get("death") or {}
    by    = year(birth.get("date") if isinstance(birth,dict) else None)
    dy    = year(death.get("date") if isinstance(death,dict) else None)
    fy    = year(bio.get("floruit"))
    wqid  = idents.get("wikidata_qid")
    auth  = idents.get("outremer_auth")
    gender= bio.get("gender")

    # ── Person ────────────────────────────────────────────────────────
    po = [("a", "crm:E21_Person")]
    if label:                   po.append(("rdfs:label", f'"{esc(label)}"'))
    for v in names.get("variants",[]):
        if v and v != label:    po.append(("skos:altLabel", f'"{esc(v)}"'))
    for n in names.get("normalized",[]):
        if n:                   po.append(("skos:hiddenLabel", f'"{esc(n)}"'))
    if wqid:                    po.append(("owl:sameAs", f"wd:{wqid}"))
    if auth:                    po.append(("crm:P1_is_identified_by", f"outremer:ID_{lid(auth)}"))
    if gender in GENDER_URI:    po.append(("crm:P2_has_type", GENDER_URI[gender]))
    if by:                      po.append(("crm:P98i_was_born", f"outremer:Birth_{lp}"))
    if dy:                      po.append(("crm:P100i_died_in", f"outremer:Death_{lp}"))
    if fy:                      po.append(("crm:P4_has_time-span", f"outremer:Floruit_{lp}"))
    for r in rels:
        if r.get("type") == "parent":
            ref = r.get("wikidata_ref") or r.get("person_id")
            if ref:
                pu = f"wd:{ref}" if not str(ref).startswith("AUTH") else uri(ref)
                po.append(("crm:P152_has_parent", pu))
    for src in prov.get("sources",[]):
        if src.get("source_file"):
            po.append(("crm:P70i_is_documented_in", f'"{esc(src["source_file"])}"'))
    triples(u, po, out)

    # ── Birth ──────────────────────────────────────────────────────────
    if by:
        triples(f"outremer:Birth_{lp}", [
            ("a", "crm:E67_Birth"),
            ("crm:P98_brought_into_life", u),
            ("crm:P4_has_time-span", f"outremer:TS_Birth_{lp}"),
        ], out)
        triples(f"outremer:TS_Birth_{lp}", [
            ("a", "crm:E52_Time-Span"),
            ("crm:P82a_begin_of_the_begin", by),
            ("crm:P82b_end_of_the_end", by),
        ], out)

    # ── Death ──────────────────────────────────────────────────────────
    if dy:
        triples(f"outremer:Death_{lp}", [
            ("a", "crm:E69_Death"),
            ("crm:P100_was_death_of", u),
            ("crm:P4_has_time-span", f"outremer:TS_Death_{lp}"),
        ], out)
        triples(f"outremer:TS_Death_{lp}", [
            ("a", "crm:E52_Time-Span"),
            ("crm:P82a_begin_of_the_begin", dy),
            ("crm:P82b_end_of_the_end", dy),
        ], out)

    # ── Floruit ────────────────────────────────────────────────────────
    if fy:
        triples(f"outremer:Floruit_{lp}", [
            ("a", "crm:E52_Time-Span"),
            ("crm:P2_has_type", "outremer:Type_Floruit"),
            ("crm:P82a_begin_of_the_begin", fy),
        ], out)

    # ── Auth identifier node ───────────────────────────────────────────
    if auth:
        triples(f"outremer:ID_{lid(auth)}", [
            ("a", "crm:E42_Identifier"),
            ("rdf:value", f'"{esc(auth)}"'),
            ("crm:P2_has_type", "outremer:Type_OutremerAuthorityID"),
        ], out)

    # ── Spouse → E85_Joining into shared family group ─────────────────
    seen_couples = set()
    for r in rels:
        if r.get("type") == "spouse":
            ref = r.get("wikidata_ref") or r.get("person_id")
            if ref:
                ids   = tuple(sorted([pid, f"WIKIDATA:{ref}" if not str(ref).startswith("AUTH") else ref]))
                if ids in seen_couples: continue
                seen_couples.add(ids)
                gl    = re.sub(r'[^A-Za-z0-9_]', '_', "_".join(ids))
                su    = f"wd:{ref}" if not str(ref).startswith("AUTH") else uri(ref)
                triples(f"outremer:FamilyGroup_{gl}", [
                    ("a", "crm:E74_Group"),
                    ("crm:P2_has_type", "outremer:Type_MaritalGroup"),
                ], out)
                triples(f"outremer:Joining_{gl}_{lp}", [
                    ("a", "crm:E85_Joining"),
                    ("crm:P143_joined", u),
                    ("crm:P144_joined_with", f"outremer:FamilyGroup_{gl}"),
                ], out)

def emit_vocab(out):
    out.write("# ── Vocabulary ──────────────────────────────────────────────────────\n")
    for uri_s, label in [
        ("outremer:Gender_Male", "Male"),
        ("outremer:Gender_Female", "Female"),
        ("outremer:Type_Floruit", "Floruit"),
        ("outremer:Type_MaritalGroup", "Marital group"),
        ("outremer:Type_OutremerAuthorityID", "Outremer Authority ID"),
    ]:
        triples(uri_s, [("a","crm:E55_Type"),("rdfs:label",f'"{label}"')], out)

def main():
    print(f"Reading {INPUT} …", flush=True)
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    total = len(data)
    print(f"  {total:,} persons", flush=True)

    print(f"Writing {OUTPUT} …", flush=True)
    with OUTPUT.open("w", encoding="utf-8") as out:
        out.write(PREFIXES)
        out.write(f"\n# Generated {datetime.now(timezone.utc).isoformat()}\n# {total:,} persons\n\n")
        emit_vocab(out)
        for i,(pid,person) in enumerate(data.items()):
            emit_person(pid, person, out)
            if (i+1) % 1000 == 0:
                print(f"  {i+1:,}/{total:,} ({(i+1)/total*100:.0f}%)", flush=True)

    mb = OUTPUT.stat().st_size / 1_048_576
    print(f"Done — {OUTPUT.name} ({mb:.1f} MB)", flush=True)

if __name__ == "__main__":
    main()
