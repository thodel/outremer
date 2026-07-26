#!/usr/bin/env python3
"""Versioned canonical, JSON-LD, Turtle, schema.org and TEI publication profiles."""
from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from rdflib import RDF, Graph, Literal, Namespace, URIRef

try:
    from scripts.evidence_model import canonical_bytes, validate_dataset
    from scripts.evidence_semantics import OUT, PROV, uri
except ModuleNotFoundError:  # direct ``python scripts/evidence_publish.py``
    from evidence_model import canonical_bytes, validate_dataset
    from evidence_semantics import OUT, PROV, uri

OWL = Namespace("http://www.w3.org/2002/07/owl#")
SCHEMA = Namespace("https://schema.org/")
TEI = "http://www.tei-c.org/ns/1.0"
PROFILE_VERSION = "1.0.0"


def publication_graph(dataset: dict) -> Graph:
    """Lossless graph: semantic triples plus canonical JSON for exact round-trip."""
    errors = validate_dataset(dataset)
    if errors:
        raise ValueError("; ".join(errors))
    graph = Graph()
    graph.bind("out", OUT)
    graph.bind("prov", PROV)
    graph.bind("schema", SCHEMA)
    graph.bind("owl", OWL)
    index = {obj["id"]: obj for obj in dataset["objects"]}
    for obj in dataset["objects"]:
        subject = uri(obj["id"])
        graph.add((subject, RDF.type, OUT[obj["type"].title().replace("_", "")]))
        graph.add((subject, OUT.localId, Literal(obj["id"])))
        graph.add((subject, OUT.profileVersion, Literal(PROFILE_VERSION)))
        graph.add((
            subject,
            OUT.canonicalJson,
            Literal(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
        ))
        if obj["type"] == "passage":
            graph.add((subject, OUT.snapshot, uri(obj["snapshot_id"])))
            graph.add((subject, OUT.locator, Literal(obj["locator"])))
        elif obj["type"] == "mention":
            graph.add((subject, OUT.passage, uri(obj["passage_id"])))
            graph.add((subject, OUT.verbatim, Literal(obj["verbatim"])))
        elif obj["type"] == "assertion":
            for passage_id in obj["passage_ids"]:
                graph.add((subject, OUT.evidencePassage, uri(passage_id)))
            graph.add((subject, OUT.subject, uri(obj["subject_id"])))
            graph.add((subject, OUT.predicate, Literal(obj["predicate"])))
        elif obj["type"] == "identity_hypothesis":
            graph.add((subject, OUT.mention, uri(obj["mention_id"])))
            for candidate in obj["candidates"]:
                graph.add((subject, OUT.candidate, uri(candidate["identity_id"])))
        elif obj["type"] == "decision":
            graph.add((subject, OUT.hypothesis, uri(obj["hypothesis_id"])))
            graph.add((subject, OUT.candidate, uri(obj["candidate_id"])))
            graph.add((subject, OUT.decisionStatus, Literal(obj["status"])))
            graph.add((subject, PROV.wasGeneratedBy, uri(obj["activity_id"])))
            # owl:sameAs is reserved for an explicit, reviewed scholarly decision.
            if (
                obj["status"] == "accepted"
                and obj.get("same_as_assertion") is True
                and index[obj["candidate_id"]].get("source_native_ids")
            ):
                for external in index[obj["candidate_id"]]["source_native_ids"].values():
                    if external.startswith("http"):
                        graph.add((uri(obj["candidate_id"]), OWL.sameAs, URIRef(external)))
    return graph


def graph_to_dataset(graph: Graph) -> dict:
    objects = [
        json.loads(str(value))
        for value in graph.objects(None, OUT.canonicalJson)
    ]
    objects.sort(key=lambda obj: obj["id"])
    return {"schema_version": "1.0.0", "objects": objects}


def discovery_projection(dataset: dict) -> dict:
    """Lossy schema.org projection for discovery only, never canonical reuse."""
    people = []
    for obj in dataset["objects"]:
        if obj["type"] not in {"person", "group"}:
            continue
        item = {
            "@type": "Person" if obj["type"] == "person" else "Organization",
            "@id": str(uri(obj["id"])),
            "name": obj["preferred_label"],
        }
        people.append(item)
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Outremer discovery projection",
        "description": (
            "Lossy discovery projection. Consult canonical JSON-LD/Turtle for "
            "evidence, uncertainty, and decision history."
        ),
        "hasPart": people,
    }


def tei_standoff(dataset: dict) -> str:
    """TEI stand-off annotations linking verbatim mentions to accepted identities."""
    index = {obj["id"]: obj for obj in dataset["objects"]}
    accepted: dict[str, str] = {}
    for decision in dataset["objects"]:
        if decision["type"] != "decision" or decision["status"] != "accepted":
            continue
        hypothesis = index[decision["hypothesis_id"]]
        accepted[hypothesis["mention_id"]] = decision["candidate_id"]
    root = ET.Element(f"{{{TEI}}}TEI")
    text = ET.SubElement(root, f"{{{TEI}}}text")
    body = ET.SubElement(text, f"{{{TEI}}}body")
    ET.SubElement(body, f"{{{TEI}}}p").text = (
        "Stand-off projection; source text remains in canonical passages."
    )
    stand_off = ET.SubElement(root, f"{{{TEI}}}standOff")
    spans = ET.SubElement(stand_off, f"{{{TEI}}}spanGrp", {"type": "outremer-mentions"})
    for mention in (obj for obj in dataset["objects"] if obj["type"] == "mention"):
        attributes = {
            "{http://www.w3.org/XML/1998/namespace}id": mention["id"].replace(":", "-"),
            "ana": str(uri(mention["id"])),
        }
        if mention["id"] in accepted:
            attributes["ref"] = str(uri(accepted[mention["id"]]))
        span = ET.SubElement(spans, f"{{{TEI}}}span", attributes)
        span.text = mention["verbatim"]
    return ET.tostring(root, encoding="unicode")


def publish(dataset: dict, output: Path) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    graph = publication_graph(dataset)
    paths = {
        "canonical": output / "canonical.json",
        "jsonld": output / "canonical.jsonld",
        "turtle": output / "canonical.ttl",
        "discovery": output / "discovery.schema.json",
        "tei": output / "mentions.tei.xml",
    }
    paths["canonical"].write_bytes(canonical_bytes(dataset))
    paths["jsonld"].write_text(graph.serialize(format="json-ld", indent=2), encoding="utf-8")
    paths["turtle"].write_text(graph.serialize(format="turtle"), encoding="utf-8")
    paths["discovery"].write_text(
        json.dumps(discovery_projection(dataset), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["tei"].write_text(tei_standoff(dataset), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    publish(json.loads(args.dataset.read_text(encoding="utf-8")), args.output)


if __name__ == "__main__":
    main()
