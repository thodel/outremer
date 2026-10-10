#!/usr/bin/env python3
"""
M19.1 (#91): name-form enrichment from the pre-1500 snapshot, with provenance.

    python scripts/enrich_authority_variants.py --snapshot data/wd-pre1500.db [--dry-run]

For every authority record that carries a Wikidata QID (asserted by
backfill_authority_qids.py, or hand-verified in #45) the snapshot's labels and
aliases in every language it holds (en, de, fr, la, it, es, nl, ar) become
name variants of the record — *Radulfus Cadomensis* for Ralph of Caen,
*Fulko von Jerusalem* for Fulk V of Anjou — each with its own provenance
(system, QID, language, label/alias, snapshot build). The precomputed
``normalized.variants`` block is extended the same way, so the linker pays
no normalisation cost at match time.

What is deliberately NOT added — the danger the issue overlooks: more
variants also raise the hit rate of the *wrong* record, because every second
crusader is a Baldwin, a Robert or a Hugh. Measured on the first run
(2026-10-10, 283 forms): eleven corpus mentions changed their top candidate
and every one was wrong — "the people of Jerusalem" → Fulk V via the alias
"Fulk, King of Jerusalem", "Franciscans of Jerusalem" → Conrad of Montferrat
via "Conrad I, King of Jerusalem", "the Hohenstaufens" → Conrad III. A title
is a description, not a name. So a form is first cut at its comma and
stripped of parentheses ("Stephen de Sancerre, Count of Sancerre" → "Stephen
de Sancerre"), then dropped if it still carries a title word in any of the
snapshot's languages or names only a realm (Jerusalem, France, Germany …)
beside the given name, and finally dropped if, after particles, honorifics
and numerals, fewer than two tokens remain: *Robert II*, *Heinrich III.*,
*Fulko*, *Radulf* stay out; *Roberto II di Fiandra*, *Heinrich der Löwe*,
*Radulfus Cadomensis* come in. Nothing existing is ever overwritten or removed.

The outcome per record is written to data/audits/authority_variant_enrichment.json.
Measure the effect with ``python -m evaluation.authority_enrichment_report``
(it relinks the fixtures with the current authority file) — M19.3 (#93).
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

from linker import normalise as link_normalise  # noqa: E402
from wikidata_snapshot import PARTICLES, Snapshot  # noqa: E402

DEFAULT_INDEX = ROOT / "scripts" / "outremer_index.json"
DEFAULT_AUDIT = ROOT / "data" / "audits" / "authority_variant_enrichment.json"
METHOD = "enrich_authority_variants v1"
SYSTEM = "wikidata-pre1500-snapshot"
HONORIFICS = {"saint", "st", "sir", "san", "sankt", "dom", "sant", "santo", "santa", "ste"}
#: A title describes an office, not a person; an alias that carries one is a
#: description Wikidata stores as a name ("Fulk, King of Jerusalem").
TITLES = {
    "king", "konig", "roi", "rey", "re", "koning", "rex", "ملك",
    "queen", "konigin", "reine", "reina", "regina", "koningin",
    "count", "graf", "comte", "conde", "conte", "graaf", "comes", "earl", "jarl", "كونت",
    "countess", "grafin", "comtesse", "condesa", "contessa", "gravin",
    "duke", "herzog", "duc", "duque", "duca", "hertog", "dux", "دوق",
    "lord", "herr", "seigneur", "sire", "senor", "signore", "heer", "dominus",
    "baron", "marquess", "marquis", "markgraf", "marchese", "marques", "margrave", "markgraaf",
    "prince", "prinz", "principe", "prins", "princeps", "امير",
    "bishop", "bischof", "eveque", "obispo", "vescovo", "bisschop", "episcopus",
    "archbishop", "erzbischof", "archeveque", "arzobispo", "arcivescovo", "aartsbisschop",
    "abbot", "abt", "abbe", "abad", "abate", "abbas", "monachus", "monk", "monch", "moine",
    "emperor", "kaiser", "empereur", "emperador", "imperatore", "keizer", "imperator",
    "patriarch", "chancellor", "kanzler", "chancelier", "canciller", "cancelliere",
    "der", "le", "the",  # left here only so "x der y" epithets are judged by what remains
}
TITLES -= {"der", "le", "the"}
#: A realm beside a given name is a title in disguise ("Pierre de France",
#: "Fulko von Jerusalem"): it names where someone ruled, not who they are.
REALMS = {
    "jerusalem", "jerusalen", "gerusalemme", "jeruzalem", "القدس", "بيت", "المقدس", "أورشليم",
    "france", "francia", "frankreich", "frankrijk", "fransa", "فرنسا",
    "germany", "alemania", "deutschland", "allemagne", "germania", "duitsland", "ألمانيا",
    "england", "inglaterra", "angleterre", "inghilterra", "engeland",
    "empire", "reich", "imperio", "impero", "rijk", "saint", "heiliges", "romisch", "romano",
}
ROMAN = re.compile(r"^(?=[ivxlc]+$)m*(c[md]|d?c{0,3})(x[cl]|l?x{0,3})(i[xv]|v?i{0,3})$")


def distinctive_tokens(form: str) -> list[str]:
    """Tokens that carry identity: no particles, honorifics or numerals.

    Plain normalisation (lowercase, no accents), not the snapshot's Latin
    folding — "Jarl" must stay "jarl" to be recognised as a title.
    """
    out = []
    for tok in link_normalise(form).split():
        if tok in PARTICLES or tok in HONORIFICS:
            continue
        if ROMAN.match(tok) or tok.isdigit():
            continue
        out.append(tok)
    return out


def clean_form(form: str) -> str:
    """The name part of a snapshot form: before the first comma, no parentheses."""
    form = re.sub(r"\s*\([^)]*\)", "", form)
    form = form.split(",", 1)[0]
    return " ".join(form.split())


def is_bare(form: str) -> bool:
    """A given name alone, with or without a numeral, names too many people."""
    return len(distinctive_tokens(form)) < 2


def is_title(form: str) -> bool:
    """An office or a realm, not a name."""
    toks = link_normalise(form).split()
    if any(t in TITLES for t in toks):
        return True
    distinct = distinctive_tokens(form)
    # given name + realm only ("Pierre de France", "Fulko von Jerusalem")
    return len(distinct) >= 2 and all(t in REALMS for t in distinct[1:])


def snapshot_forms(snapshot: Snapshot, qid: str) -> list[tuple[str, str, str]]:
    return [tuple(r) for r in snapshot._con.execute(
        "SELECT name, lang, kind FROM names WHERE qid=? ORDER BY lang, kind, name", (qid,))]


def enrich_record(record: dict, snapshot: Snapshot) -> dict[str, Any]:
    qid = (record.get("identifiers") or {}).get("wikidata_qid")
    report: dict[str, Any] = {"authority_id": record["authority_id"],
                              "preferred_label": record["preferred_label"], "qid": qid,
                              "added": [], "skipped_bare": [], "skipped_title": [],
                              "skipped_known": 0}
    if not qid:
        report["skipped"] = "no QID"
        return report
    known = {link_normalise(v) for v in [record.get("preferred_label", ""), *(record.get("variants") or [])] if v}
    variants: list[str] = list(record.get("variants") or [])
    provenance: dict[str, list[dict]] = record.setdefault("variant_provenance", {})
    norm_block = record.setdefault("normalized", {})
    norm_variants: list[str] = list(norm_block.get("variants") or [])
    norm_seen = set(norm_variants)
    seen_forms: set[str] = set()
    for raw, lang, kind in snapshot_forms(snapshot, qid):
        form = clean_form(raw)
        key = link_normalise(form)
        if not key or key in seen_forms:
            continue
        seen_forms.add(key)
        if key in known:
            report["skipped_known"] += 1
            continue
        if is_title(form):
            report["skipped_title"].append(raw)
            continue
        if is_bare(form):
            report["skipped_bare"].append(raw)
            continue
        variants.append(form)
        provenance[form] = [{"system": SYSTEM, "locator": qid, "lang": lang, "kind": kind,
                             "snapshot": snapshot.version}]
        if key not in norm_seen:
            norm_variants.append(key)
            norm_seen.add(key)
        report["added"].append({"form": form, "lang": lang, "kind": kind})
    record["variants"] = sorted(set(variants), key=str.casefold)
    norm_block["variants"] = sorted(set(norm_variants))
    return report


def enrich(index: dict, snapshot: Snapshot) -> tuple[dict, dict]:
    rows = [enrich_record(r, snapshot) for r in index.get("persons", [])]
    counts = {
        "records_with_qid": sum(1 for r in rows if r.get("qid")),
        "records_enriched": sum(1 for r in rows if r.get("added")),
        "forms_added": sum(len(r.get("added") or []) for r in rows),
        "forms_skipped_bare": sum(len(r.get("skipped_bare") or []) for r in rows),
        "forms_skipped_title": sum(len(r.get("skipped_title") or []) for r in rows),
        "forms_skipped_known": sum(r.get("skipped_known", 0) for r in rows),
        "by_lang": {},
    }
    for r in rows:
        for a in r.get("added") or []:
            counts["by_lang"][a["lang"]] = counts["by_lang"].get(a["lang"], 0) + 1
    audit = {"schema_version": 1, "method": METHOD, "snapshot": snapshot.version,
             "ran_at": datetime.now(timezone.utc).isoformat(), "counts": counts,
             "records": [r for r in rows if r.get("qid")]}
    return index, audit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    ap.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    index = json.loads(args.index.read_text(encoding="utf-8"))
    index, audit = enrich(index, Snapshot(args.snapshot))
    print(json.dumps(audit["counts"], indent=2, ensure_ascii=False))
    for r in audit["records"]:
        if r["added"]:
            print(f"  {r['authority_id']:<12} {r['preferred_label']:<36} +{len(r['added'])}: "
                  + ", ".join(a["form"] for a in r["added"][:6]) + (" …" if len(r["added"]) > 6 else ""))
    if not args.dry_run:
        args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.index} and {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
