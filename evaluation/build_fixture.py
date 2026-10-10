"""
evaluation/build_fixture.py

Build adjudicated-mode fixtures from Human-in-the-Loop decisions
(data/decisions.json) plus a snapshot of the current pipeline predictions
(site/data/<doc_id>.json). Scholar adjudications thereby become regression
gold: future prompt/model changes are measured against what humans already
judged.

Where the same (person, authority_id) pair received both accepts and
rejects, majority wins; ties are dropped (they are disagreements, not gold).
A decision flagged ``supersedes`` retires every earlier decision for its
pair first (M19.0, #97), and ``unresolved`` casts no vote — a superseding
``unresolved`` therefore removes the pair from the gold altogether.

Usage (from repo root):
    python -m evaluation.build_fixture            # all docs with decisions
    python -m evaluation.build_fixture --doc-id X # one document
    python -m evaluation.build_fixture --relink   # authority links from the
                                                  # current linker, not the
                                                  # nightly's snapshot

``--relink`` keeps the extracted persons and the Wikidata answers exactly as
the nightly produced them, but recomputes the authority links with the code
in this checkout (evaluation/_pipeline.relink) — so a fixture never carries
links made by an older operating point (M19.3).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from validate_decisions import effective_decisions  # noqa: E402

ACCEPT = {"accept"}
REJECT = {"reject", "not_a_person", "wrong_era", "is_group"}


def _wikidata_snapshot(
    site_data_dir: Path, doc_id: str, mentions: list[str]
) -> dict[str, dict]:
    """Snapshot wikidata reconciliation candidates for the given mentions."""
    wm_path = site_data_dir / "wikidata_matches.json"
    if not wm_path.exists():
        return {}
    all_matches = json.loads(wm_path.read_text())
    doc_matches = all_matches.get(doc_id) or {}
    from evaluation.metrics import normalise_name

    wanted = {normalise_name(m) for m in mentions}
    return {
        key: {
            "candidates": [
                {"qid": c.get("qid"), "score": c.get("score")}
                for c in (entry.get("candidates") or [])
            ]
        }
        for key, entry in doc_matches.items()
        if normalise_name(key) in wanted
    }


def _link_snapshot(links: list[dict]) -> list[dict]:
    """The part of a link the fixture keeps: mention, top id, candidate ids."""
    return [
        {
            "person": link.get("person", ""),
            "top_candidate": (
                {
                    # site/data uses "outremer_id"; accept legacy
                    # "authority_id" defensively
                    "outremer_id": (link.get("top_candidate") or {}).get("outremer_id")
                    or (link.get("top_candidate") or {}).get("authority_id")
                }
                if link.get("top_candidate")
                else None
            ),
            # candidate ids beyond the top, for diagnosis (#42)
            "candidates": [
                {"outremer_id": c.get("outremer_id") or c.get("authority_id")}
                for c in (link.get("candidates") or [])
                if c.get("outremer_id") or c.get("authority_id")
            ],
        }
        for link in links
    ]


def build_fixtures(
    decisions_path: Path,
    site_data_dir: Path,
    *,
    only_doc_id: str | None = None,
    relink: bool = False,
) -> list[dict]:
    raw = json.loads(decisions_path.read_text())
    decisions = effective_decisions(raw)
    superseded = len(raw) - len(decisions)

    # (doc_id, person, auth_id) → [+1 accept / -1 reject votes]
    votes: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for d in decisions:
        doc_id = (d.get("doc_id") or "").strip()
        person = " ".join((d.get("person") or "").split())  # collapse \n artifacts
        auth_id = (d.get("outremer_id") or "").strip()
        decision = (d.get("decision") or "").strip()
        if not doc_id or not person or not auth_id:
            continue
        if only_doc_id and doc_id != only_doc_id:
            continue
        if decision in ACCEPT:
            votes[(doc_id, person, auth_id)].append(1)
        elif decision in REJECT:
            votes[(doc_id, person, auth_id)].append(-1)
        elif decision == "unresolved":
            votes[(doc_id, person, auth_id)]  # the key exists, no vote

    per_doc: dict[str, dict] = defaultdict(lambda: {"accepted": [], "rejected": []})
    dropped_ties = 0
    retired = 0
    for (doc_id, person, auth_id), vs in votes.items():
        if not vs:
            retired += 1  # unresolved: neither identity nor non-identity
            continue
        score = sum(vs)
        if score > 0:
            per_doc[doc_id]["accepted"].append([person, auth_id])
        elif score < 0:
            per_doc[doc_id]["rejected"].append([person, auth_id])
        else:
            dropped_ties += 1

    fixtures = []
    for doc_id, gold in sorted(per_doc.items()):
        fixture = {
            "doc_id": doc_id,
            "mode": "adjudicated",
            "accepted": sorted(gold["accepted"]),
            "rejected": sorted(gold["rejected"]),
        }
        reviewed_mentions = [p for p, _ in gold["accepted"] + gold["rejected"]]
        wd_snap = _wikidata_snapshot(site_data_dir, doc_id, reviewed_mentions)
        pred_path = site_data_dir / f"{doc_id}.json"
        if pred_path.exists():
            data = json.loads(pred_path.read_text())
            persons = [p.get("name", "") for p in data.get("persons", [])]
            links = data.get("links", [])
            if relink:
                from evaluation._pipeline import load_authority_lookup
                from evaluation._pipeline import relink as _relink

                links = _relink(persons, load_authority_lookup())
            fixture["predictions"] = {
                "wikidata": wd_snap,
                "persons": persons,
                "links": _link_snapshot(links),
            }
        fixtures.append(fixture)

    if superseded:
        print(f"note: {superseded} decision(s) superseded by later adjudications")
    if retired:
        print(f"note: {retired} pair(s) unresolved — in neither accepted nor rejected")
    if dropped_ties:
        print(f"note: dropped {dropped_ties} tied (disputed) pairs")
    return fixtures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--decisions", default=str(REPO_ROOT / "data" / "decisions.json"))
    ap.add_argument("--site-data", default=str(REPO_ROOT / "site" / "data"))
    ap.add_argument("--out-dir", default=str(FIXTURES_DIR))
    ap.add_argument("--doc-id", default=None)
    ap.add_argument("--relink", action="store_true",
                    help="recompute authority links with the current linker")
    args = ap.parse_args(argv)

    fixtures = build_fixtures(
        Path(args.decisions), Path(args.site_data), only_doc_id=args.doc_id,
        relink=args.relink,
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for fx in fixtures:
        out = out_dir / f"{fx['doc_id']}.json"
        # Preserve hand-curated gold across regenerations (M9.1): full-mode
        # gold_persons and provenance notes are scholar/manual work that the
        # decisions file does not contain.
        if out.exists():
            existing = json.loads(out.read_text())
            for key in ("gold_persons", "gold_provenance"):
                if key in existing and key not in fx:
                    fx[key] = existing[key]
            if existing.get("mode") == "full":
                fx["mode"] = "full"
        out.write_text(json.dumps(fx, indent=2, ensure_ascii=False) + "\n")
        print(
            f"wrote {out.name}: {len(fx['accepted'])} accepted, "
            f"{len(fx['rejected'])} rejected"
            + ("" if "predictions" in fx else " (no prediction snapshot)")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
