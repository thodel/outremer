#!/usr/bin/env python3
"""Pinned-repository TEI adapter for Syriaca.org persons and SPEAR factoids."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.integrations.open_authorities import ADAPTER_VERSION, canonical_json
from scripts.source_registry import require_operation

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI}
REPOSITORY = "https://github.com/srophe/syriaca-data.git"
LIVE_ENDPOINTS = (
    "https://syriaca.org/api/person/10",
    "https://syriaca.org/person/10/tei",
    "https://syriaca.org/oai",
)


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"-?(\d{3,4})", value)
    return int(match.group(1)) if match else None


def _attrs(element: ET.Element, names: tuple[str, ...]) -> dict[str, str]:
    return {name: element.attrib[name] for name in names if element.attrib.get(name)}


@dataclass(frozen=True)
class PinnedSource:
    repository: str
    commit: str
    path: str
    checksum: str
    adapter_version: str = f"{ADAPTER_VERSION}+syriaca-tei-v1"


class SyriacaTeiAdapter:
    def __init__(self, repository: str = REPOSITORY, commit: str = "") -> None:
        require_operation("syriaca", "snapshot")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("Syriaca snapshot requires a full 40-character Git commit")
        self.repository = repository
        self.commit = commit

    def parse_file(self, path: Path, *, relative_path: str | None = None) -> dict[str, Any]:
        raw = path.read_bytes()
        return self.parse_bytes(raw, relative_path=relative_path or path.as_posix())

    def load_checkout(
        self, checkout: Path, relative_roots: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        """Consume XML only from the verified pinned checkout."""
        verify_checkout(checkout, self.commit)
        records = []
        for relative_root in relative_roots:
            for path in sorted((checkout / relative_root).glob("**/*.xml")):
                relative_path = path.relative_to(checkout).as_posix()
                record = self.parse_file(path, relative_path=relative_path)
                if self.relevant_to_pilot(record):
                    records.append(record)
        return records

    def parse_bytes(self, raw: bytes, *, relative_path: str) -> dict[str, Any]:
        root = ET.fromstring(raw)
        uri = _text(root.find(".//tei:publicationStmt/tei:idno[@type='URI']", NS))
        licence = root.find(".//tei:publicationStmt/tei:availability/tei:licence", NS)
        record = {
            "source": "syriaca",
            "record_type": "spear" if "/spear/" in relative_path else "person",
            "uri": uri.removesuffix("/tei"),
            "xml_ids": sorted({
                element.attrib[f"{{{XML}}}id"]
                for element in root.iter()
                if element.attrib.get(f"{{{XML}}}id")
            }),
            "names": [
                {
                    "text": _text(name),
                    "xml_id": name.attrib.get(f"{{{XML}}}id"),
                    "language": name.attrib.get(f"{{{XML}}}lang"),
                    "source": name.attrib.get("source"),
                    "responsibility": name.attrib.get("resp"),
                }
                for name in root.findall(".//tei:persName", NS)
                if _text(name)
            ],
            "dates": [
                {
                    "text": _text(element),
                    "element": element.tag.rsplit("}", 1)[-1],
                    **_attrs(element, ("when", "notBefore", "notAfter", "from", "to", "source")),
                }
                for tag in ("birth", "death", "floruit", "date")
                for element in root.findall(f".//tei:{tag}", NS)
            ],
            "relations": [
                {
                    "name": relation.attrib.get("name"),
                    "active": relation.attrib.get("active"),
                    "passive": relation.attrib.get("passive"),
                    "mutual": relation.attrib.get("mutual"),
                    "source": relation.attrib.get("source"),
                }
                for relation in root.findall(".//tei:relation", NS)
            ],
            "events": [
                {
                    "xml_id": event.attrib.get(f"{{{XML}}}id"),
                    "text": _text(event),
                    **_attrs(event, ("when", "notBefore", "notAfter", "from", "to", "source")),
                    "places": [
                        {"text": _text(place), "ref": place.attrib.get("ref")}
                        for place in event.findall(".//tei:placeName", NS)
                    ],
                }
                for event in root.findall(".//tei:event", NS)
            ],
            "bibliography": [
                {
                    "xml_id": bibl.attrib.get(f"{{{XML}}}id"),
                    "text": _text(bibl),
                    "pointers": [ptr.attrib.get("target") for ptr in bibl.findall(".//tei:ptr", NS)],
                }
                for bibl in root.findall(".//tei:listBibl/tei:bibl", NS)
            ],
            "revision": [
                {
                    "when": change.attrib.get("when"),
                    "who": change.attrib.get("who"),
                    "text": _text(change),
                }
                for change in root.findall(".//tei:revisionDesc/tei:change", NS)
            ],
            "licence": {
                "target": licence.attrib.get("target") if licence is not None else None,
                "statement": _text(licence),
                "third_party_material": bool(
                    licence is not None
                    and "copyrighted material" in _text(licence).casefold()
                ),
            },
            "source_pointers": sorted({
                pointer
                for element in root.iter()
                for pointer in element.attrib.get("source", "").split()
                if pointer
            }),
            "snapshot": PinnedSource(
                repository=self.repository,
                commit=self.commit,
                path=relative_path,
                checksum=hashlib.sha256(raw).hexdigest(),
            ).__dict__,
            "editorial_status": (
                "Syriaca interpretation mapped as a source assertion; "
                "not collapsed into canonical truth."
            ),
        }
        return record

    def relevant_to_pilot(
        self,
        record: dict,
        *,
        not_before: int = 1000,
        not_after: int = 1400,
        region_terms: tuple[str, ...] = (
            "jerusalem", "antioch", "edessa", "aleppo", "damascus", "mosul",
            "levant", "mediterranean",
        ),
    ) -> bool:
        years = [
            year
            for date in record["dates"] + record["events"]
            for key in ("when", "notBefore", "notAfter", "from", "to")
            if (year := _year(date.get(key))) is not None
        ]
        temporal = not years or (min(years) <= not_after and max(years) >= not_before)
        haystack = json.dumps(record, ensure_ascii=False).casefold()
        geographic = any(term in haystack for term in region_terms)
        return temporal and geographic

    def write_snapshot(self, records: list[dict], path: Path) -> Path:
        payload = {
            "repository": self.repository,
            "commit": self.commit,
            "adapter_version": f"{ADAPTER_VERSION}+syriaca-tei-v1",
            "records": sorted(records, key=lambda item: (item["uri"], item["snapshot"]["path"])),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(canonical_json(payload))
        temporary.replace(path)
        return path

    @staticmethod
    def attribution(record: dict) -> dict:
        return {
            "credit": "Syriaca.org: The Syriac Reference Portal",
            "record_uri": record["uri"],
            "licence": record["licence"]["target"],
            "repository": record["snapshot"]["repository"],
            "commit": record["snapshot"]["commit"],
            "third_party_material_requires_review": record["licence"][
                "third_party_material"
            ],
        }


def verify_checkout(path: Path, expected_commit: str) -> None:
    actual = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual != expected_commit:
        raise ValueError(f"Syriaca checkout is {actual}, expected pinned {expected_commit}")


def health_check_live_endpoints(opener=urlopen) -> list[dict]:
    """Report endpoint health only; repository snapshots remain authoritative."""
    results = []
    for url in LIVE_ENDPOINTS:
        request = Request(url, headers={"User-Agent": "outremer-research/0.1"})
        try:
            with opener(request, timeout=15) as response:
                status = response.status
        except HTTPError as exc:
            status = exc.code
        except (URLError, TimeoutError):
            status = None
        results.append({"url": url, "status": status, "usable": status == 200})
    return results


class DisabledLiveApiAdapter:
    def fetch(self, *_args, **_kwargs):
        raise RuntimeError(
            "Syriaca live API adapter is disabled; use the pinned Git repository snapshot"
        )
