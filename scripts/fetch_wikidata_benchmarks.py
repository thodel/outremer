#!/usr/bin/env python3
"""
M19.2 tranche B (#92): rights-clean benchmark lists for the coverage audit.

    python scripts/fetch_wikidata_benchmarks.py [--out data/audits/benchmarks]

Riley-Smith, *The First Crusaders, 1095–1131* and Murray, *The Crusader
Kingdom of Jerusalem: A Dynastic History 1099–1125* are the reference works
the issue names. Both are in copyright; their lists are not ingested here
(data/sources/registry.json: reference-only). What this fetches instead is
Wikidata's own answer to the same questions — CC0, registered as
open-integrable — so the count is reproducible by anyone:

    first-crusade, second-crusade, third-crusade
        humans linked to the crusade item by P607 (conflict), P1344
        (participant in) or as P710 (participant) of the crusade
    latin-east-1095-1131
        humans who died 1095–1131 and held an office (P39) of the Latin East
        — king or queen of Jerusalem, prince of Antioch, count of Tripoli or
        Edessa, prince of Galilee, Latin patriarch of Jerusalem — or carry
        the noble title (P97) of one of those polities: Riley-Smith's span,
        Murray's polities. (Citizenship and residence are not recorded for
        the period: that query returned nothing.)

Each list records the query, the time of the fetch and the CC0 licence, and
is matched against the authority file by scripts/audit_authority_coverage.py
— by QID first, which is exact, then by name.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.source_registry import require_operation  # noqa: E402

ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "outremer-research/0.1 (+https://github.com/thodel/outremer; tobias.hodel@unibe.ch)"
DEFAULT_OUT = ROOT / "data" / "audits" / "benchmarks"

CRUSADES = {"first-crusade": "Q51649", "second-crusade": "Q51654", "third-crusade": "Q51655"}
REALMS = ["Q93180", "Q243631", "Q244137", "Q213129"]   # Jerusalem, Antioch, Tripoli, Edessa

_HEAD = ('OPTIONAL { ?p wdt:P569 ?birth } OPTIONAL { ?p wdt:P570 ?death } '
         'OPTIONAL { ?p schema:description ?desc FILTER(LANG(?desc)="en") } '
         'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr,de,la". } }')


def crusade_query(qid: str) -> str:
    return ("SELECT DISTINCT ?p ?pLabel ?birth ?death ?desc WHERE { "
            f"{{ ?p wdt:P607 wd:{qid} }} UNION {{ ?p wdt:P1344 wd:{qid} }} UNION {{ wd:{qid} wdt:P710 ?p }} "
            "?p wdt:P31 wd:Q5 . " + _HEAD)


OFFICES = ["King of Jerusalem", "Queen of Jerusalem", "Prince of Antioch", "Count of Tripoli",
           "Count of Edessa", "Prince of Galilee", "Latin Patriarch of Jerusalem",
           "Constable of Jerusalem", "Lord of Sidon", "Lord of Beirut", "Lord of Caesarea",
           "Lord of Oultrejordain", "Lord of Toron", "Lord of Ramla", "Count of Jaffa and Ascalon"]


def latin_east_query() -> str:
    labels = ", ".join(f'"{o}"@en' for o in OFFICES)
    return ("SELECT DISTINCT ?p ?pLabel ?birth ?death ?desc WHERE { "
            f"?pos rdfs:label ?pl . FILTER(?pl IN ({labels})) "
            "{ ?p wdt:P39 ?pos } UNION { ?p wdt:P97 ?pos } "
            "?p wdt:P31 wd:Q5 . ?p wdt:P570 ?d . FILTER(YEAR(?d) >= 1095 && YEAR(?d) <= 1131) " + _HEAD)


def sparql(query: str, timeout: int = 90) -> list[dict]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["results"]["bindings"]


def to_figures(rows: list[dict]) -> list[dict]:
    people: dict[str, dict] = {}
    for x in rows:
        qid = x["p"]["value"].rsplit("/", 1)[-1]
        label = x.get("pLabel", {}).get("value") or qid
        entry = people.setdefault(qid, {"preferred_label": label, "wikidata": qid,
                                        "birth_year": None, "death_year": None, "description": ""})
        for key, var in (("birth_year", "birth"), ("death_year", "death")):
            v = x.get(var, {}).get("value")
            if v and entry[key] is None:
                try:
                    entry[key] = int(v[:4]) if not v.startswith("-") else -int(v[1:5])
                except ValueError:
                    pass
        if not entry["description"]:
            entry["description"] = x.get("desc", {}).get("value", "")
    return sorted(people.values(), key=lambda e: (e["death_year"] or 9999, e["preferred_label"]))


def fetch_all(out_dir: Path) -> dict[str, int]:
    require_operation("wikidata", "snapshot")
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    specs = {**{k: (crusade_query(q), f"humans linked to {k.replace('-', ' ')} ({q}) by P607, P1344 or P710")
                for k, q in CRUSADES.items()},
             "latin-east-1095-1131": (latin_east_query(),
                                      "humans †1095–1131 holding an office (P39) or noble title (P97) "
                                      "of the Latin East: " + ", ".join(OFFICES))}
    for name, (query, scope) in specs.items():
        try:
            figures = to_figures(sparql(query))
            status = "ok"
        except Exception as exc:  # the endpoint times out on heavy joins
            figures, status = [], f"failed: {exc}"
        payload = {
            "schema_version": 1, "id": f"wikidata-{name}", "source": "wikidata",
            "licence": "CC0 1.0", "scope": scope, "query": query, "endpoint": ENDPOINT,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "status": status,
            "match_by": ["wikidata", "preferred_label"],
            "figures": figures,
        }
        (out_dir / f"wikidata-{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        counts[name] = len(figures)
        print(f"  {name:<24} {len(figures):>4} persons  [{status}]")
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    fetch_all(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
