#!/usr/bin/env python3
"""
M19.4 part 1 (#94): backfill Wikidata QIDs for the authority file, offline.

    python scripts/backfill_authority_qids.py --snapshot data/wd-pre1500.db [--dry-run]

Every record is resolved against the pre-1500 snapshot (the vendored resolver
in scripts/wikidata_snapshot.py; no network). The outcome is one of three and
is written down for every record in data/audits/authority_qid_backfill.json:

    asserted      exactly one candidate agrees with the record on every
                  structured field it has (given name, regnal numeral,
                  toponym or epithet, period 1050–1350) and either matches the
                  name at ≥ 0.85 or is pinned by numeral AND toponym; it goes
                  into identifiers.wikidata_qid with provenance
    hypothesised  one or more candidates agree structurally but none stands
                  alone (a tie, a bare two-token name, a numeral the record
                  does not have); they go into identifiers.wikidata_candidates
                  and nowhere else
    none          no candidate agrees on the structured fields

A label-equal tie is never asserted — the lesson of #158 (Baldwin of Ibelin
d. 1187 vs d. 1313). Existing QIDs are kept and re-verified, never replaced.

Why structure, not only the score: the snapshot's English label for Q333306
is "Robert II" with "Count of Flanders (1065-1111)" as description and the
toponym only in French/Spanish/Italian aliases, so the string score is 0.7
against fourteen other "Robert II". The record knows its numeral and its
toponym; checking both against names *and description* is what identifies him.
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

from wikidata_snapshot import PARTICLES, Snapshot, normalise  # noqa: E402

DEFAULT_INDEX = ROOT / "scripts" / "outremer_index.json"
DEFAULT_AUDIT = ROOT / "data" / "audits" / "authority_qid_backfill.json"
METHOD = "backfill_authority_qids v1"
PERIOD = (1050, 1350)       # the corpus: First Crusade to the fall of Acre, with slack
ASSERT_SCORE = 0.85
HONORIFICS = {"saint", "st", "sir", "san", "sankt", "dom", "lord", "count", "duke", "king"}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9,
         "x": 10, "xi": 11, "xii": 12}


def _numeral(text: str) -> int | None:
    """The regnal numeral a name form carries, Roman or Arabic, else None."""
    for tok in normalise(text).split():
        if tok in ROMAN:
            return ROMAN[tok]
    m = re.search(r"\b(\d{1,2})\b", text)
    return int(m.group(1)) if m else None


def _first_token(name: str) -> str | None:
    toks = [t for t in normalise(name).split() if t not in HONORIFICS]
    return toks[0] if toks else None


def _discriminator(record: dict) -> tuple[str, str | None]:
    """(kind, text) of what tells this record apart from namesakes."""
    name = record.get("name") or {}
    if name.get("toponym"):
        return "toponym", name["toponym"]
    if name.get("epithet"):
        return "epithet", name["epithet"]
    rest = name.get("rest") or ""
    if rest and any(t in PARTICLES for t in normalise(rest).split()):
        return "toponym", rest           # "de Borneil", "de Lacy": a place
    if rest:
        return "surname", rest           # "Petersson", "Marshal": weak
    return "none", None


def _given(record: dict) -> str:
    name = record.get("name") or {}
    return name.get("name") or name.get("given") or record["preferred_label"].split()[0]


class Checker:
    def __init__(self, snapshot: Snapshot):
        self.snapshot = snapshot
        self._con = snapshot._con

    def names(self, qid: str) -> list[str]:
        return [r[0] for r in self._con.execute("SELECT name FROM names WHERE qid=?", (qid,))]

    def candidates(self, record: dict, limit: int = 50) -> dict[str, dict]:
        """Union of the resolver's answers for the label and every variant."""
        pool: dict[str, dict] = {}
        queries = [record["preferred_label"], *(record.get("variants") or [])]
        for i, q in enumerate(queries):
            res = self.snapshot.resolve(q, limit=limit if i == 0 else 20)
            for c in res.get("candidates") or []:
                if c["qid"] not in pool or c["score"] > pool[c["qid"]]["score"]:
                    pool[c["qid"]] = dict(c)
        return pool

    def check(self, record: dict, cand: dict) -> dict[str, Any]:
        forms = [cand["label"], *self.names(cand["qid"])]
        desc = cand.get("description") or ""
        haystack = normalise(" ".join(forms + [desc]))
        hay_tokens = set(haystack.split())

        given = normalise(_given(record))
        ok_given = any(_first_token(f) == given for f in forms) or given in {
            t for f in forms for t in normalise(f).split()[:1]
        }

        record_num = _numeral(record["preferred_label"])
        label_num = _numeral(cand["label"])
        form_nums = {n for n in (_numeral(f) for f in forms + [desc]) if n is not None}
        if record_num is None:
            # The record names no numeral. A numbered candidate may still be
            # the person (the record may simply omit it), so this does not
            # break consistency; decide() keeps it a hypothesis.
            ok_regnal = None
        else:
            ok_regnal = record_num in form_nums and (label_num in (None, record_num))

        kind, disc = _discriminator(record)
        if disc is None:
            ok_disc = None
        else:
            disc_tokens = {t for t in normalise(disc).split() if t not in PARTICLES and t != "the"}
            ok_disc = bool(disc_tokens) and (
                disc_tokens <= hay_tokens
                or any(normalise(disc) in normalise(f) for f in forms)
                or any(t in haystack for t in disc_tokens if len(t) >= 5)
            )

        death = cand.get("death_year")
        birth = cand.get("birth_year")
        in_period = death is not None and PERIOD[0] <= death <= PERIOD[1] and (birth is None or birth <= 1300)

        consistent = bool(ok_given) and ok_regnal is not False and ok_disc is not False and in_period
        return {
            "qid": cand["qid"], "label": cand["label"], "description": desc,
            "birth_year": birth, "death_year": death, "score": cand["score"],
            "matched": cand.get("matched"),
            "given": ok_given, "regnal": ok_regnal, "discriminator": ok_disc,
            "discriminator_kind": kind, "period": in_period, "consistent": consistent,
        }

    def decide(self, record: dict) -> dict[str, Any]:
        pool = self.candidates(record)
        # Consistent first, best score first, then the earlier death year:
        # among namesakes the one nearer the corpus's period is the more
        # useful hypothesis to show first.
        checked = sorted((self.check(record, c) for c in pool.values()),
                         key=lambda r: (-r["consistent"], -r["score"],
                                        r["death_year"] or 9999, r["qid"]))
        consistent = [r for r in checked if r["consistent"]]
        kind, _ = _discriminator(record)
        verdict, qid, why = "none", None, "no candidate agrees with the record's structured fields"
        if consistent:
            top = consistent[0]
            rivals = [r for r in consistent[1:] if r["score"] >= top["score"] - 0.1]
            pinned = top["regnal"] is True and top["discriminator"] is True
            strong = top["score"] >= ASSERT_SCORE and top["discriminator"] is True
            if rivals:
                verdict, why = "hypothesised", f"{len(rivals) + 1} candidates agree equally well"
            elif top["regnal"] is None and _numeral(record["preferred_label"]) is None and \
                    _numeral(top["label"]) is not None:
                verdict, why = "hypothesised", "the candidate carries a numeral the record does not"
            elif kind in ("none", "surname") and top["score"] < 1.0:
                verdict, why = "hypothesised", "a bare name without toponym or numeral"
            elif kind in ("none", "surname"):
                verdict, why = "hypothesised", "an exact two-token name, but nothing pins the person"
            elif strong or pinned:
                verdict, qid = "asserted", top["qid"]
                why = ("name match ≥ 0.85 with the toponym verified" if strong
                       else "numeral and toponym both verified")
            else:
                verdict, why = "hypothesised", f"structurally consistent but score {top['score']} < {ASSERT_SCORE}"
        return {
            "authority_id": record["authority_id"],
            "preferred_label": record["preferred_label"],
            "existing_qid": (record.get("identifiers") or {}).get("wikidata_qid"),
            "verdict": verdict, "qid": qid, "why": why,
            "candidates": checked[:8],
        }


def backfill(index: dict, snapshot: Snapshot) -> tuple[dict, dict]:
    checker = Checker(snapshot)
    rows = []
    counts = {"asserted": 0, "hypothesised": 0, "none": 0, "kept_existing": 0, "existing_not_reproduced": 0}
    for record in index.get("persons", []):
        decision = checker.decide(record)
        ids = record.setdefault("identifiers", {})
        existing = ids.get("wikidata_qid")
        if existing:
            counts["kept_existing"] += 1
            if decision["qid"] != existing:
                counts["existing_not_reproduced"] += 1
                decision["note"] = f"existing QID {existing} kept; backfill would say {decision['verdict']} {decision['qid'] or ''}".strip()
        elif decision["verdict"] == "asserted":
            ids["wikidata_qid"] = decision["qid"]
            ids["wikidata_qid_provenance"] = {
                "system": "wikidata-pre1500-snapshot", "snapshot": snapshot.version,
                "method": METHOD, "status": "asserted", "why": decision["why"],
            }
            ids.pop("wikidata_candidates", None)
        elif decision["verdict"] == "hypothesised":
            ids["wikidata_candidates"] = [
                {"qid": c["qid"], "label": c["label"], "death_year": c["death_year"], "score": c["score"]}
                for c in decision["candidates"] if c["consistent"]
            ]
            ids.pop("wikidata_qid", None)
        else:
            ids.pop("wikidata_candidates", None)
        counts[decision["verdict"]] += 1
        rows.append(decision)
    audit = {
        "schema_version": 1, "method": METHOD, "snapshot": snapshot.version,
        "ran_at": datetime.now(timezone.utc).isoformat(), "period": list(PERIOD),
        "assert_score": ASSERT_SCORE, "counts": counts, "records": rows,
    }
    return index, audit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snapshot", required=True, type=Path, help="pre-1500 snapshot (SQLite)")
    ap.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    ap.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    index = json.loads(args.index.read_text(encoding="utf-8"))
    index, audit = backfill(index, Snapshot(args.snapshot))
    print(json.dumps(audit["counts"], indent=2))
    for row in audit["records"]:
        if row["verdict"] == "asserted":
            top = row["candidates"][0]
            print(f"  {row['authority_id']:<12} {row['preferred_label']:<40} → {row['qid']} {top['label']} (†{top['death_year']}, {top['score']})")
    if not args.dry_run:
        args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.index} and {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
