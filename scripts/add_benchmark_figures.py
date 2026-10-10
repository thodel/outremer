#!/usr/bin/env python3
"""
M19.2 tranche A (#92): add the benchmark figures the authority file lacks.

    python scripts/add_benchmark_figures.py --snapshot data/wd-pre1500.db [--dry-run]

The #99 coverage audit named 14 benchmark figures of the First Crusade and
its narrative traditions; the file held one (Godfrey of Bouillon). This adds
the other thirteen, plus Tancred, whose mention in Riley-Smith had been
accepted against Constance of Toulouse (#97) because no record existed.

Each new record gets the next free AUTH:CR number, a QID with provenance
that says where the identity comes from — the hand-checked benchmark list
(#99), the offline resolver's `asserted` verdict (backfill_authority_qids),
or a hand verification recorded here (#92) — the benchmark's own variants,
and the snapshot's name forms through enrich_authority_variants (so
*Albertus Aquensis*, *Foucher de Chartres* and *أسامة بن منقذ* come along,
each with provenance). Every form is attributed; nothing existing changes.

Variants listed here by hand are scholar-sourced and may be bare ("Tancred",
"Ekkehard"): in a crusade text these names mean these men, and the mentions
they must reach are exactly that bare. That is a deliberate exception to the
rule enrich_authority_variants applies to snapshot forms.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backfill_authority_qids import Checker  # noqa: E402
from enrich_authority_variants import enrich_record  # noqa: E402
from linker import normalise  # noqa: E402
from wikidata_snapshot import Snapshot  # noqa: E402

DEFAULT_INDEX = ROOT / "scripts" / "outremer_index.json"
DEFAULT_BENCHMARK = ROOT / "data" / "audits" / "epic19-benchmark-figures.json"
DEFAULT_AUDIT = ROOT / "data" / "audits" / "epic19-tranche-a.json"
ISSUE = "issue:92"

#: Identity decisions that the benchmark list does not carry and the resolver
#: cannot make alone (a tie, or a bare name). Each is a hand verification.
HAND = {
    "Alexios I Komnenos": ("Q41600", "Byzantine emperor 1081–1118, †1118; the resolver finds the "
                                     "exact name but a bare two-token name never asserts"),
    "Ibn al-Athir": ("Q334854", "ʿAlī ʿIzz al-Dīn ibn al-Athīr, historian (1160–1233), author of "
                                "al-Kāmil fī al-tārīkh; the resolver ties three brothers of the name"),
    "Anna Komnene": ("Q179284", "the historian (1083–1154), as in the benchmark list; the resolver "
                                "ties her with a namesake daughter of John II"),
    "Tancred, Prince of Galilee": ("Q51720", "the crusader (c. 1075–1112); the resolver ties him with "
                                             "his grandfather Tancred of Hauteville (†1041)"),
    "Ibn al-Qalanisi": ("Q1356575", "Abū Yaʿlā Ḥamza ibn al-Qalānisī, Damascus chronicler (†1160); the "
                                    "resolver finds the exact label but reads 'Ibn' as a given name"),
}
#: Added beside the benchmark list: the mention the gold repair (#97) left
#: without a record.
EXTRA = [{"preferred_label": "Tancred, Prince of Galilee",
          "variants": ["Tancred", "Tancred of Hauteville", "Tancred of Galilee"],
          "tradition": "Latin Christian", "role": "participant"}]


def parse_name(label: str) -> dict[str, Any]:
    """The structured name block the Omeka import gave existing records."""
    if label.startswith("Ibn ") or "," in label:
        return {"raw": label, "name": label.split(",")[0], "pattern": None}
    m = re.match(r"^(\S+) ([IVX]+) of (.+)$", label)
    if m:
        return {"raw": label, "name": m.group(1), "regnal": m.group(2), "toponym": m.group(3),
                "pattern": "regnal_of"}
    m = re.match(r"^(\S+) of (.+)$", label)
    if m:
        return {"raw": label, "name": m.group(1), "toponym": m.group(2), "pattern": "of"}
    m = re.match(r"^(\S+) the (.+)$", label)
    if m:
        return {"raw": label, "name": m.group(1), "epithet": m.group(2), "pattern": "the"}
    m = re.match(r"^(\S+) (.+)$", label)
    if m:
        return {"raw": label, "given": m.group(1), "rest": m.group(2), "pattern": "space"}
    return {"raw": label, "name": label, "pattern": None}


def next_number(index: dict) -> int:
    nums = [int(re.sub(r"\D", "", p["authority_id"]) or 0) for p in index.get("persons", [])]
    return max(nums, default=0) + 1


def present(index: dict, figure: dict) -> str | None:
    names = {}
    for rec in index.get("persons", []):
        for n in [rec.get("preferred_label"), *(rec.get("variants") or [])]:
            if n:
                names.setdefault(normalise(n), rec["authority_id"])
    for n in [figure["preferred_label"], *(figure.get("variants") or [])]:
        if normalise(n) in names:
            return names[normalise(n)]
    return None


def identity(figure: dict, checker: Checker, record: dict) -> tuple[str | None, dict | None, dict]:
    """(qid, provenance, resolver decision) for a figure."""
    label = figure["preferred_label"]
    decision = checker.decide(record)
    if figure.get("wikidata"):
        return figure["wikidata"], {"system": "github-issue", "locator": "issue:99", "status": "asserted",
                                    "why": "benchmark list of #99 (Wikidata entity search, checked 2026-07-30)"}, decision
    if label in HAND:
        qid, why = HAND[label]
        return qid, {"system": "github-issue", "locator": ISSUE, "status": "asserted",
                     "why": f"hand-verified in #92: {why}"}, decision
    if decision["verdict"] == "asserted":
        return decision["qid"], {"system": "wikidata-pre1500-snapshot", "snapshot": checker.snapshot.version,
                                 "method": "backfill_authority_qids v1", "status": "asserted",
                                 "why": decision["why"]}, decision
    return None, None, decision


def add_figures(index: dict, figures: list[dict], snapshot: Snapshot) -> tuple[dict, dict]:
    checker = Checker(snapshot)
    number = next_number(index)
    added, skipped = [], []
    for figure in figures:
        label = figure["preferred_label"]
        where = present(index, figure)
        if where:
            skipped.append({"preferred_label": label, "present_as": where})
            continue
        aid = f"AUTH:CR{number}"
        number += 1
        variants = sorted({label, *(figure.get("variants") or [])} - {label}, key=str.casefold)
        record: dict[str, Any] = {
            "authority_id": aid,
            "preferred_label": label,
            "identifiers": {"project_identifier": aid.split(":")[1]},
            "name": parse_name(label),
            "variants": variants,
            "normalized": {"preferred": normalise(label), "variants": sorted({normalise(v) for v in variants})},
            "type": "person",
            "provenance": {"source_files": [], "source_system": "manual",
                           "note": f"added {datetime.now(timezone.utc).date().isoformat()} per issue #92 "
                                   f"(M19.2 tranche A: benchmark figure of #99, {figure.get('tradition', '')}, "
                                   f"{figure.get('role', '')})"},
            "variant_provenance": {n: [{"system": "github-issue", "locator": ISSUE}] for n in [label, *variants]},
        }
        qid, prov, decision = identity(figure, checker, record)
        if qid:
            record["identifiers"]["wikidata_qid"] = qid
            record["identifiers"]["wikidata_qid_provenance"] = prov
        elif decision["verdict"] == "hypothesised":
            record["identifiers"]["wikidata_candidates"] = [
                {"qid": c["qid"], "label": c["label"], "death_year": c["death_year"], "score": c["score"]}
                for c in decision["candidates"] if c["consistent"]]
        enrichment = enrich_record(record, snapshot) if qid else {"added": []}
        index["persons"].append(record)
        added.append({"authority_id": aid, "preferred_label": label, "qid": qid,
                      "identity": prov["system"] if prov else decision["verdict"],
                      "resolver": {"verdict": decision["verdict"], "qid": decision["qid"], "why": decision["why"]},
                      "variants_listed": variants,
                      "forms_from_snapshot": [a["form"] for a in enrichment["added"]]})
    audit = {"schema_version": 1, "issue": ISSUE, "snapshot": snapshot.version,
             "ran_at": datetime.now(timezone.utc).isoformat(),
             "counts": {"added": len(added), "skipped_present": len(skipped),
                        "forms_from_snapshot": sum(len(a["forms_from_snapshot"]) for a in added)},
             "added": added, "skipped": skipped}
    return index, audit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    ap.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    ap.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    index = json.loads(args.index.read_text(encoding="utf-8"))
    figures = json.loads(args.benchmark.read_text(encoding="utf-8"))["figures"] + EXTRA
    index, audit = add_figures(index, figures, Snapshot(args.snapshot))
    print(json.dumps(audit["counts"], indent=2))
    for a in audit["added"]:
        print(f"  {a['authority_id']:<12} {a['preferred_label']:<28} {a['qid'] or '—':<10} {a['identity']:<26} "
              f"+{len(a['forms_from_snapshot'])} forms")
    for s_ in audit["skipped"]:
        print(f"  present: {s_['preferred_label']} as {s_['present_as']}")
    if not args.dry_run:
        args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.index} and {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
