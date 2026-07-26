#!/usr/bin/env python3
"""RDF/JSON-LD projection for assertion-level evidence and uncertainty."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pyshacl import validate
from rdflib import RDF, XSD, BNode, Graph, Literal, Namespace, URIRef

OUT = Namespace("https://outremer.example/ns/")
PROV = Namespace("http://www.w3.org/ns/prov#")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
CRMINF = Namespace("http://www.cidoc-crm.org/crminf/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
BASE = "https://outremer.example/id/"
SHAPES = Path(__file__).resolve().parents[1] / "schema" / "evidence-first-v1.shacl.ttl"

CERTAINTY = {"certain", "probable", "possible", "unlikely", "unknown"}
POLARITY = {"affirmed", "negated", "disputed"}
REVIEW_STATUS = {"unreviewed", "accepted", "rejected", "disputed", "superseded"}
INFERENCE = {"source_explicit", "source_implicit", "extracted", "editorial_inference"}
RELIABILITY = {"high", "medium", "low", "unassessed"}


def uri(local_id: str) -> URIRef:
    return URIRef(BASE + local_id.replace("outremer:", "").replace(":", "/"))


def _literal_year(value: int | None) -> Literal | None:
    return Literal(value, datatype=XSD.integer) if value is not None else None


def _add_optional(graph: Graph, subject, predicate, value) -> None:
    if value is not None:
        graph.add((subject, predicate, value))


def dataset_to_graph(dataset: dict) -> Graph:
    graph = Graph()
    graph.bind("out", OUT)
    graph.bind("prov", PROV)
    graph.bind("crm", CRM)
    graph.bind("crminf", CRMINF)
    graph.bind("geo", GEO)
    index = {obj["id"]: obj for obj in dataset["objects"]}
    for obj in dataset["objects"]:
        subject = uri(obj["id"])
        kind = obj["type"]
        class_name = {
            "assertion": "Assertion", "passage": "Passage", "decision": "Decision",
            "activity": "Activity", "snapshot": "Snapshot", "person": "Person",
            "group": "Group", "mention": "Mention", "identity_hypothesis": "IdentityHypothesis",
        }.get(kind, kind.title().replace("_", ""))
        graph.add((subject, RDF.type, OUT[class_name]))
        graph.add((subject, OUT.localId, Literal(obj["id"])))

        if kind == "assertion":
            for passage_id in obj.get("passage_ids", []):
                graph.add((subject, OUT.evidencePassage, uri(passage_id)))
            graph.add((subject, OUT.predicate, Literal(obj.get("predicate", ""))))
            graph.add((subject, OUT.assertionObject, Literal(str(obj.get("object", "")))))
            semantics = obj.get("semantics", {})
            for key, allowed in (
                ("source_certainty", CERTAINTY), ("polarity", POLARITY),
                ("inference", INFERENCE), ("source_reliability", RELIABILITY),
                ("review_status", REVIEW_STATUS),
            ):
                value = semantics.get(key)
                if value not in allowed:
                    raise ValueError(f"{obj['id']}: invalid {key} {value!r}")
                graph.add((subject, OUT[key], Literal(value)))
            for key in ("extractor_confidence", "reconciliation_score", "editorial_confidence"):
                _add_optional(
                    graph, subject, OUT[key],
                    Literal(semantics[key], datatype=XSD.decimal) if key in semantics else None,
                )
            temporal = obj.get("asserted_time", {})
            for key in ("notBefore", "notAfter", "from", "to", "when"):
                _add_optional(graph, subject, OUT[key], _literal_year(temporal.get(key)))
            _add_optional(
                graph, subject, OUT.originalDateText,
                Literal(temporal["original_text"]) if temporal.get("original_text") else None,
            )
            _add_optional(
                graph, subject, OUT.calendarNote,
                Literal(temporal["calendar_note"]) if temporal.get("calendar_note") else None,
            )
            for candidate in obj.get("place_candidates", []):
                node = BNode()
                graph.add((subject, OUT.placeCandidate, node))
                graph.add((node, OUT.sourceString, Literal(candidate["source_string"])))
                graph.add((node, OUT.candidateUri, URIRef(candidate["uri"])))
                graph.add((node, OUT.rank, Literal(candidate["rank"], datatype=XSD.integer)))
                _add_optional(graph, node, OUT.validFrom, _literal_year(candidate.get("valid_from")))
                _add_optional(graph, node, OUT.validTo, _literal_year(candidate.get("valid_to")))
                _add_optional(
                    graph, node, GEO.asWKT,
                    Literal(candidate["geometry"], datatype=GEO.wktLiteral)
                    if candidate.get("geometry") else None,
                )
                graph.add((node, OUT.spatialPrecision, Literal(candidate["spatial_precision"])))
            provenance = obj.get("provenance", {})
            graph.add((subject, PROV.wasDerivedFrom, uri(provenance["snapshot_id"])))
            graph.add((subject, PROV.wasGeneratedBy, uri(provenance["generation_activity_id"])))
            if provenance.get("review_activity_id"):
                graph.add((subject, OUT.reviewActivity, uri(provenance["review_activity_id"])))

        if kind == "snapshot":
            for field in ("source_created_at", "source_published_at", "ingested_at"):
                if obj.get(field):
                    graph.add((subject, OUT[field], Literal(obj[field], datatype=XSD.dateTime)))

        if kind == "activity":
            graph.add((subject, OUT.responsibleAgent, Literal(obj["agent"])))
            graph.add((subject, PROV.startedAtTime, Literal(obj["started_at"], datatype=XSD.dateTime)))
            if obj.get("adapter_version"):
                graph.add((subject, OUT.adapterVersion, Literal(obj["adapter_version"])))

        if kind == "decision":
            graph.add((subject, OUT.decisionStatus, Literal(obj["status"])))
            graph.add((subject, OUT.reviewActivity, uri(obj["activity_id"])))
            activity = index.get(obj["activity_id"])
            if activity:
                activity_uri = uri(activity["id"])
                graph.add((activity_uri, RDF.type, OUT.Activity))
                graph.add((activity_uri, OUT.responsibleAgent, Literal(activity["agent"])))
    return graph


def assertion_from_graph(graph: Graph, assertion_id: str) -> dict[str, Any]:
    subject = uri(assertion_id)

    def value(predicate):
        item = graph.value(subject, predicate)
        return item.toPython() if item is not None else None

    asserted_time = {
        key: value(OUT[key])
        for key in ("notBefore", "notAfter", "from", "to", "when")
        if value(OUT[key]) is not None
    }
    if value(OUT.originalDateText):
        asserted_time["original_text"] = value(OUT.originalDateText)
    if value(OUT.calendarNote):
        asserted_time["calendar_note"] = value(OUT.calendarNote)
    candidates = []
    for node in graph.objects(subject, OUT.placeCandidate):
        candidates.append({
            "source_string": graph.value(node, OUT.sourceString).toPython(),
            "uri": str(graph.value(node, OUT.candidateUri)),
            "rank": graph.value(node, OUT.rank).toPython(),
            "valid_from": (
                graph.value(node, OUT.validFrom).toPython()
                if graph.value(node, OUT.validFrom) else None
            ),
            "valid_to": (
                graph.value(node, OUT.validTo).toPython()
                if graph.value(node, OUT.validTo) else None
            ),
            "geometry": (
                str(graph.value(node, GEO.asWKT)) if graph.value(node, GEO.asWKT) else None
            ),
            "spatial_precision": graph.value(node, OUT.spatialPrecision).toPython(),
        })
    return {
        "id": assertion_id,
        "passage_ids": [
            str(item).replace(BASE, "outremer:").replace("/", ":", 1)
            for item in graph.objects(subject, OUT.evidencePassage)
        ],
        "semantics": {
            key: value(OUT[key])
            for key in (
                "source_certainty", "polarity", "inference", "source_reliability",
                "review_status", "extractor_confidence", "reconciliation_score",
                "editorial_confidence",
            )
            if value(OUT[key]) is not None
        },
        "asserted_time": asserted_time,
        "place_candidates": sorted(candidates, key=lambda item: item["rank"]),
        "provenance": {
            "snapshot_uri": str(graph.value(subject, PROV.wasDerivedFrom)),
            "generation_activity_uri": str(graph.value(subject, PROV.wasGeneratedBy)),
            "review_activity_uri": (
                str(graph.value(subject, OUT.reviewActivity))
                if graph.value(subject, OUT.reviewActivity) else None
            ),
        },
    }


def validate_graph(graph: Graph, shapes_path: Path = SHAPES) -> tuple[bool, str]:
    conforms, _, report = validate(
        graph, shacl_graph=str(shapes_path), inference="rdfs", advanced=True
    )
    return bool(conforms), str(report)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
