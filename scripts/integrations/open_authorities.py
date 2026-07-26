#!/usr/bin/env python3
"""Snapshot-aware pilot adapters for Wikidata, FactGrid, GND and Pleiades."""
from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.source_registry import require_operation

ADAPTER_VERSION = "open-authorities-v1"
USER_AGENT = "outremer-research/0.1 (+https://github.com/thodel/outremer)"


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def checksum(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def normalise_label(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.casefold().split())


def request_json(
    url: str,
    *,
    attempts: int = 3,
    opener: Callable = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> Any:
    """Fetch JSON with a declared user agent and bounded exponential backoff."""
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with opener(request, timeout=30) as response:
                return json.loads(response.read())
        except (HTTPError, URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            sleeper(2 ** attempt)
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class Snapshot:
    source_id: str
    retrieval_time: str
    source_version: str
    adapter_version: str
    records: list[dict]
    checksum: str

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "retrieval_time": self.retrieval_time,
            "source_version": self.source_version,
            "adapter_version": self.adapter_version,
            "records": self.records,
            "checksum": self.checksum,
        }


class BaseAdapter:
    source_id = ""
    licence = ""
    attribution = ""

    def __init__(self) -> None:
        require_operation(self.source_id, "snapshot")

    def map_record(self, raw: dict) -> dict:
        raise NotImplementedError

    def build_snapshot(
        self, raw_records: list[dict], *, retrieval_time: str, source_version: str
    ) -> Snapshot:
        records = sorted(
            (self.map_record(record) for record in raw_records),
            key=lambda record: record["source_uri"],
        )
        content = {
            "source_id": self.source_id,
            "source_version": source_version,
            "adapter_version": ADAPTER_VERSION,
            "records": records,
        }
        return Snapshot(
            source_id=self.source_id,
            retrieval_time=retrieval_time,
            source_version=source_version,
            adapter_version=ADAPTER_VERSION,
            records=records,
            checksum=checksum(content),
        )

    def write_snapshot(self, snapshot: Snapshot, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_json(snapshot.as_dict())
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
        return path

    @staticmethod
    def load_last_verified(path: Path) -> Snapshot:
        """Offline fallback: load, but never mutate, the last verified snapshot."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Snapshot(**raw)


def _wikibase_value(snak: dict) -> Any:
    value = snak.get("datavalue", {}).get("value")
    if isinstance(value, dict):
        if "id" in value:
            return value["id"]
        if "time" in value:
            return {"time": value["time"], "precision": value.get("precision")}
    return value


def _wikibase_statements(entity: dict) -> list[dict]:
    statements = []
    for prop, claims in sorted(entity.get("claims", {}).items()):
        for claim in claims:
            statements.append({
                "property": prop,
                "value": _wikibase_value(claim.get("mainsnak", {})),
                "rank": claim.get("rank", "normal"),
                "qualifiers": {
                    key: [_wikibase_value(snak) for snak in values]
                    for key, values in sorted(claim.get("qualifiers", {}).items())
                },
                "references": [
                    {
                        key: [_wikibase_value(snak) for snak in values]
                        for key, values in sorted(reference.get("snaks", {}).items())
                    }
                    for reference in claim.get("references", [])
                ],
            })
    return statements


class WikidataAdapter(BaseAdapter):
    source_id = "wikidata"
    licence = "CC0-1.0"
    attribution = "Wikidata contributors"

    def map_record(self, raw: dict) -> dict:
        qid = raw["id"]
        return {
            "source": self.source_id,
            "source_id": qid,
            "source_uri": f"https://www.wikidata.org/entity/{qid}",
            "revision": raw.get("lastrevid"),
            "labels": {key: value["value"] for key, value in raw.get("labels", {}).items()},
            "aliases": {
                key: [item["value"] for item in values]
                for key, values in raw.get("aliases", {}).items()
            },
            "statements": _wikibase_statements(raw),
            "licence": self.licence,
            "attribution": self.attribution,
        }


class FactGridAdapter(WikidataAdapter):
    source_id = "factgrid"
    attribution = "FactGrid contributors"

    def map_record(self, raw: dict) -> dict:
        record = super().map_record(raw)
        record["source"] = self.source_id
        record["source_uri"] = f"https://database.factgrid.de/entity/{raw['id']}"
        record["attribution"] = self.attribution
        return record


class GNDAdapter(BaseAdapter):
    source_id = "gnd"
    licence = "CC0-1.0"
    attribution = "Deutsche Nationalbibliothek (GND)"

    def map_record(self, raw: dict) -> dict:
        identifier = str(raw["id"])
        return {
            "source": self.source_id,
            "source_id": identifier,
            "source_uri": f"https://d-nb.info/gnd/{identifier}",
            "preferred_name": raw["preferred_name"],
            "variant_names": sorted(set(raw.get("variant_names", []))),
            "dates": raw.get("dates", {}),
            "professions": raw.get("professions", []),
            "record_version": raw.get("record_version"),
            "licence": self.licence,
            "attribution": self.attribution,
        }


class PleiadesAdapter(BaseAdapter):
    source_id = "pleiades"
    licence = "CC-BY-3.0"
    attribution = "Pleiades contributors"

    def map_record(self, raw: dict) -> dict:
        identifier = str(raw["id"]).rsplit("/", 1)[-1]
        return {
            "source": self.source_id,
            "source_id": identifier,
            "source_uri": f"https://pleiades.stoa.org/places/{identifier}",
            "title": raw.get("title"),
            "names": [
                {
                    "name": name.get("attested") or name.get("romanized"),
                    "language": name.get("language"),
                    "time_periods": name.get("timePeriods", []),
                    "provenance": name.get("provenance"),
                }
                for name in raw.get("names", [])
            ],
            "locations": [
                {
                    "geometry": location.get("geometry"),
                    "time_periods": location.get("timePeriods", []),
                    "provenance": location.get("provenance"),
                }
                for location in raw.get("locations", [])
            ],
            "connections": raw.get("connections", []),
            "medieval_scope_warning": (
                "Pleiades is an ancient-world gazetteer; a candidate link may remain unresolved "
                "for a medieval place."
            ),
            "licence": self.licence,
            "attribution": self.attribution,
        }


def candidate_features(query: dict, candidate: dict) -> dict:
    """Precision-oriented features; label equality is evidence, never identity."""
    query_names = {
        normalise_label(name)
        for name in [query.get("preferred_name", ""), *query.get("variant_names", [])]
        if name
    }
    candidate_names = {
        normalise_label(name)
        for name in [
            candidate.get("preferred_name", ""),
            candidate.get("title", ""),
            *candidate.get("variant_names", []),
            *candidate.get("labels", {}).values(),
        ]
        if name
    }
    return {
        "label_overlap": sorted(query_names & candidate_names),
        "date_overlap": bool(query.get("dates") and candidate.get("dates")),
        "place_context_available": bool(
            candidate.get("locations") or candidate.get("statements")
        ),
        "source_distinct_id": f"{candidate['source']}:{candidate['source_id']}",
        "identity_asserted": False,
        "requires_curator_review": True,
        "false_positive_risks": [
            "homonymous person/place",
            "incompatible chronology",
            "source scope mismatch",
        ],
    }
