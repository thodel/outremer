#!/usr/bin/env python3
"""
build_review_worksheet.py
─────────────────────────
Generate a scholar-facing review worksheet for repairing and growing the
authority adjudication gold (issues #98 / #36).

Why this exists
───────────────
The authority gold is 7 accepted pairs against 48 rejected, and #98 found
that six of the seven accepts link the *wrong person*. Two consequences:

1. The accepted pairs must be re-adjudicated before any enrichment work
   (#91 / #92) can be measured — they are currently the only positive
   evidence the evaluation has, and they are wrong.
2. Even repaired, 7 positive pairs is too few. A linker proposing nothing
   already scores 0.873 on this gold; without more accepts, agreement
   cannot distinguish a working linker from a disabled one.

The worksheet therefore has two parts: **repair** (adjudicate the disputed
accepts) and **grow** (a ranked queue of unreviewed candidates, highest
confidence first, so a review session yields the most positive gold per
hour spent).

Nothing here decides anything. It assembles evidence — mention, source
context, proposed authority record, and competing candidates — so a
historian can judge. Decisions go back through the normal Explorer export
→ ``data/decisions.json`` round-trip.

Usage (from repo root):
    python scripts/build_review_worksheet.py
    python scripts/build_review_worksheet.py --queue-size 40 --out docs/REVIEW_WORKSHEET.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ACCEPT = {"accept"}
REJECT = {"reject", "not_a_person", "wrong_era", "is_group"}
EXCLUDE_DOCS = {"wikidata_matches", "authority", "index"}


def _norm(s: str) -> str:
    return " ".join((s or "").split()).casefold()


def load_authority(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text())
    entries = data.get("persons") or data.get("entities") or []
    return {e.get("authority_id"): e for e in entries if e.get("authority_id")}


def load_documents(site_data: Path) -> dict[str, dict[str, Any]]:
    docs = {}
    for f in sorted(site_data.glob("*.json")):
        if any(k in f.stem for k in EXCLUDE_DOCS):
            continue
        d = json.loads(f.read_text())
        if "links" in d:
            docs[d["doc_id"]] = d
    return docs


def adjudicated_keys(decisions: list[dict]) -> set[tuple[str, str, str]]:
    """(doc_id, normalised person, authority id) already reviewed."""
    return {
        (
            (d.get("doc_id") or "").strip(),
            _norm(d.get("person") or ""),
            (d.get("outremer_id") or "").strip(),
        )
        for d in decisions
        if d.get("decision")
    }


def collect_accepts(decisions: list[dict]) -> list[dict]:
    """Accepted authority pairs, majority vote, ties dropped as disputes."""
    votes: dict[tuple[str, str, str], int] = {}
    for d in decisions:
        aid = (d.get("outremer_id") or "").strip()
        if not aid.startswith("AUTH:"):
            continue
        key = (
            (d.get("doc_id") or "").strip(),
            " ".join((d.get("person") or "").split()),
            aid,
        )
        decision = (d.get("decision") or "").strip()
        if decision in ACCEPT:
            votes[key] = votes.get(key, 0) + 1
        elif decision in REJECT:
            votes[key] = votes.get(key, 0) - 1
    return [
        {"doc_id": k[0], "person": k[1], "authority_id": k[2]}
        for k, v in votes.items()
        if v > 0
    ]


def context_for(doc: dict[str, Any], person: str) -> str:
    for p in doc.get("persons", []):
        if _norm(p.get("name", "")) == _norm(person):
            return " ".join((p.get("context") or "").split())[:200]
    return ""


def candidates_for(doc: dict[str, Any], person: str) -> list[dict]:
    for link in doc.get("links", []):
        if _norm(link.get("person", "")) == _norm(person):
            return link.get("candidates") or []
    return []


def build_repair_section(
    accepts: list[dict], docs: dict[str, dict], authority: dict[str, dict]
) -> list[str]:
    lines = [
        "## Part 1 — Repair: re-adjudicate the accepted pairs",
        "",
        "These are every currently-**accepted** authority pair. #98 found the",
        "mention and the linked authority record name different people in six",
        "of seven cases. Each row needs one of: **confirm**, **reject**, or",
        "**relink** to a different `AUTH:` id (or a note that no suitable",
        "record exists — that becomes an authority-coverage item for #92).",
        "",
    ]
    for a in sorted(accepts, key=lambda x: x["person"].casefold()):
        doc = docs.get(a["doc_id"], {})
        rec = authority.get(a["authority_id"], {})
        label = rec.get("preferred_label", "(id not present in authority file)")
        mismatch = _norm(label) != _norm(a["person"])
        flag = "🔴 **name mismatch**" if mismatch else "🟢 names agree"
        ctx = context_for(doc, a["person"])
        others = [
            c for c in candidates_for(doc, a["person"])
            if c.get("outremer_id") != a["authority_id"]
        ][:3]

        extracted = any(
            _norm(p.get("name", "")) == _norm(a["person"])
            for p in doc.get("persons", [])
        )
        lines += [
            f"### {a['person']} → `{a['authority_id']}`",
            "",
            f"- **Authority record says:** {label}  — {flag}",
            f"- **Document:** `{a['doc_id']}`",
        ]
        if ctx:
            lines.append(f"- **Source context:** “…{ctx}…”")
        if not extracted:
            lines.append(
                "- ⚠️ **This mention is no longer extracted from the document.** "
                "The pipeline cannot propose this link either way, so the pair "
                "affects the metric only as a permanent miss. Worth deciding "
                "whether the mention *should* be extracted (an extraction gap, "
                "#33) or whether the pair should simply be retired."
            )
        if rec.get("variants"):
            lines.append(
                "- **Recorded variants:** "
                + ", ".join(str(v) for v in rec["variants"][:6])
            )
        if others:
            lines.append("- **Other candidates the linker offered:**")
            for c in others:
                lines.append(
                    f"    - `{c.get('outremer_id')}` {c.get('outremer_name')} "
                    f"(score {c.get('score')})"
                )
        lines += [
            "",
            "| verdict | relink to | note |",
            "|---|---|---|",
            "| confirm / reject / relink | `AUTH:____` | |",
            "",
        ]
    return lines


def build_growth_section(
    docs: dict[str, dict], reviewed: set[tuple[str, str, str]], queue_size: int
) -> list[str]:
    rows = []
    for doc_id, doc in docs.items():
        for link in doc.get("links", []):
            top = link.get("top_candidate")
            if not top:
                continue
            aid = top.get("outremer_id") or top.get("authority_id") or ""
            if not aid.startswith("AUTH:"):
                continue
            person = link.get("person", "")
            if (doc_id, _norm(person), aid) in reviewed:
                continue
            rows.append(
                {
                    "doc_id": doc_id,
                    "person": person,
                    "authority_id": aid,
                    "authority_name": top.get("outremer_name", ""),
                    "score": float(link.get("confidence") or 0.0),
                    "status": link.get("status", ""),
                    "context": context_for(doc, person),
                }
            )
    rows.sort(key=lambda r: -r["score"])
    top_rows = rows[:queue_size]

    lines = [
        "## Part 2 — Grow: unreviewed candidates, highest confidence first",
        "",
        f"{len(rows)} unreviewed authority proposals exist; the {len(top_rows)} "
        "strongest are listed. Reviewing these is the fastest way to create",
        "**positive** gold, which is what the evaluation currently lacks —",
        "7 accepts against 48 rejects means a linker proposing nothing already",
        "scores 0.873.",
        "",
        "Accepting or rejecting each is useful; accepts are worth more.",
        "",
        "| # | mention | proposed authority record | score | document | context |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(top_rows, 1):
        ctx = (r["context"][:70] + "…") if len(r["context"]) > 70 else r["context"]
        lines.append(
            f"| {i} | **{r['person']}** | `{r['authority_id']}` {r['authority_name']} "
            f"| {r['score']:.2f} | {r['doc_id'][:26]} | {ctx} |"
        )
    lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--decisions", default=str(REPO_ROOT / "data" / "decisions.json"))
    ap.add_argument("--site-data", default=str(REPO_ROOT / "site" / "data"))
    ap.add_argument("--authority", default=str(REPO_ROOT / "scripts" / "outremer_index.json"))
    ap.add_argument("--queue-size", type=int, default=30)
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "AUTHORITY_REVIEW_WORKSHEET.md"))
    args = ap.parse_args(argv)

    decisions = json.loads(Path(args.decisions).read_text())
    docs = load_documents(Path(args.site_data))
    authority = load_authority(Path(args.authority))
    accepts = collect_accepts(decisions)
    reviewed = adjudicated_keys(decisions)

    lines = [
        "# Authority adjudication — scholarly review worksheet",
        "",
        "> Generated by `scripts/build_review_worksheet.py`. Regenerate after",
        "> each review round; do not hand-edit.",
        "",
        "**For:** Jochen Burgtorf, Laura Morreale, Tobias Hodel",
        "",
        "## Why you are being asked",
        "",
        "The pipeline's linking quality is scored against pairs you previously",
        "adjudicated. An audit (#98) found that **six of the seven accepted**",
        "authority pairs link a mention to the record of a *different person*.",
        "Because accepted pairs are the only positive evidence in the gold, the",
        "evaluation currently cannot tell a working linker from one that",
        "proposes nothing at all — both score about 0.87.",
        "",
        "Repairing Part 1 restores the metric's meaning. Part 2 grows it, which",
        "matters just as much: 7 positive examples is too few to measure",
        "anything, and authority enrichment (#91/#92) is blocked until both are",
        "done.",
        "",
        "Return decisions through the Explorer's **Export decisions** button so",
        "they flow back via `data/decisions.json`. No file here needs editing",
        "by hand.",
        "",
        f"**Corpus:** {len(docs)} documents · **authority file:** {len(authority)} records",
        f" · **already adjudicated:** {len(reviewed)} pairs",
        "",
        "---",
        "",
    ]
    lines += build_repair_section(accepts, docs, authority)
    lines += ["---", ""]
    lines += build_growth_section(docs, reviewed, args.queue_size)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    print(f"  Part 1: {len(accepts)} accepted pairs to re-adjudicate")
    print(f"  Part 2: {args.queue_size} unreviewed candidates queued")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
