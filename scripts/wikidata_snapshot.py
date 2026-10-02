"""Offline QID resolution against the pre-1500 Wikidata snapshot (M17.1, #83).

Vendored from `thodel/wikidata_pre1500_mcp` (`db.py`, commit 141f2ac), which is
the source of truth: the MCP server and this file must answer a name the same
way, or the fleet and the nightly disagree about who a person is. Keep them in
sync; `tests/test_wikidata_snapshot.py` pins the cases both were measured on.

The snapshot is a SQLite file built by that repository's `build_db.py`: every
Wikidata item that is an instance of human with a date of death before 1500,
with labels, aliases and descriptions. Resolution touches **no network at all**,
which is what #83 asks for, and every answer carries the snapshot's build date,
so a reconciliation can be reproduced against the same data.

Why it replaces the live SPARQL path: a nightly depended on a public endpoint's
mood, a cache miss could not be told from "no such person", and the live scorer
answered *Sanda Mihaela Popescu, researcher* for the word "Popes" — a 21st-century
person cannot be in this snapshot at all.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

NO_CANDIDATES = "no_candidates"
MATCH = "match"

#: Connectives that join a name to a place or a father. They may support a match
#: and must never make one: scoring on them alone returned "Jean de Vaunoise"
#: for "Albertus de Morra" (measured 2026-10-02).
PARTICLES = frozenset("""
de of von van der den du da di del dela della le la les el al il ibn bin ben bar
the sir saint st und and y e o zu zum vom aus dem das
""".split())

#: A Roman numeral, 1–3999 — checked before folding, because u/v would turn
#: Henry V into "henry u" and i/j would equate II with IJ.
_ROMAN = re.compile(r"^m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})$")


def is_roman_numeral(token: str) -> bool:
    token = token.casefold()
    return bool(token) and bool(_ROMAN.fullmatch(token))


def _fold_token(token: str) -> str:
    stripped = unicodedata.normalize("NFKD", token.casefold())
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    if is_roman_numeral(stripped):
        return stripped
    return (stripped.replace("v", "u").replace("j", "i")
            .replace("æ", "ae").replace("œ", "oe"))


def normalise(name: str) -> str:
    """Fold a name per token, so a regnal numeral survives the medieval fold."""
    cleaned = re.sub(r"[^\w\s]", " ", name or "")
    return " ".join(_fold_token(t) for t in cleaned.split() if t)


def _distinctive(tokens) -> set[str]:
    return {t for t in tokens
            if is_roman_numeral(t) or (t not in PARTICLES and len(t) > 1)}


def score(query: str, variant: str) -> float:
    """1.0 only for an exact fold; a shared particle alone scores nothing."""
    q, v = normalise(query), normalise(variant)
    if not q or not v:
        return 0.0
    if q == v:
        return 1.0
    q_core, v_core = _distinctive(set(q.split())), _distinctive(set(v.split()))
    if not q_core or not v_core:
        return 0.0
    if q_core <= v_core:
        return 0.85 if len(q_core) > 1 else 0.7
    shared = q_core & v_core
    if not shared:
        prefixed = sum(any(w.startswith(t) or t.startswith(w) for w in v_core)
                       for t in q_core)
        return 0.4 * prefixed / len(q_core) if prefixed else 0.0
    return 0.5 + 0.3 * len(shared) / len(q_core | v_core)


class Snapshot:
    """A read-only handle on the snapshot file."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        if not self.path.exists():
            raise FileNotFoundError(f"Wikidata snapshot not found: {self.path}")
        self._con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True,
                                    check_same_thread=False)
        self._con.row_factory = sqlite3.Row

    @property
    def version(self) -> str:
        """The build date, which every answer carries as its provenance."""
        row = self._con.execute(
            "SELECT value FROM snapshot WHERE key='built_at'").fetchone()
        return row[0] if row else "unknown"

    def info(self) -> dict:
        return {row["key"]: row["value"]
                for row in self._con.execute("SELECT key, value FROM snapshot")}

    def _fts_expression(self, name: str) -> str:
        tokens = [re.sub(r'"', "", t) for t in normalise(name).split()]
        tokens = sorted(_distinctive(set(tokens))) or tokens
        return " OR ".join(f'"{t}"*' for t in tokens)

    def resolve(self, name: str, limit: int = 3, min_score: float = 0.4) -> dict:
        """Candidates for a name, as a dict that can say "nothing matched".

        The envelope is the point: the live path returned `[]` both for "asked,
        and this person is not in Wikidata" and for "never asked", so a document
        could look reconciled when nothing had happened (#83).
        """
        expression = self._fts_expression(name)
        if not expression:
            return {"status": NO_CANDIDATES, "snapshot": self.version,
                    "candidates": [], "reason": "no searchable token in the name"}
        rows = self._con.execute(
            "SELECT f.qid, f.name, p.label, p.description, p.birth_year, p.death_year "
            "FROM names_fts f JOIN persons p ON p.qid = f.qid "
            "WHERE names_fts MATCH ? LIMIT 400", (expression,)).fetchall()

        best: dict[str, dict] = {}
        for row in rows:
            value = score(name, row["name"])
            if value < min_score:
                continue
            if row["qid"] not in best or value > best[row["qid"]]["score"]:
                best[row["qid"]] = {
                    "qid": row["qid"],
                    "label": row["label"] or row["qid"],
                    "description": row["description"] or "",
                    "url": f"https://www.wikidata.org/wiki/{row['qid']}",
                    "score": round(value, 3),
                    "birth_year": row["birth_year"],
                    "death_year": row["death_year"],
                    "matched": row["name"],
                }
        candidates = sorted(best.values(), key=lambda c: (-c["score"], c["qid"]))[:limit]
        return {"status": MATCH if candidates else NO_CANDIDATES,
                "snapshot": self.version, "candidates": candidates}
