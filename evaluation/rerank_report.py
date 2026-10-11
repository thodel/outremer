"""
M21.2 / M21.4 (#126, #128): measure the reranker veto on the corpus.

    OUTREMER_CAPABILITY_RERANKER=true python -m evaluation.rerank_report [--floor 0.75] [--min-relevance 0.25]

Needs GPUStack (runs on tei). Relinks every current document with the
fuzzy linker alone and with the veto, and scores both against
data/audits/linking-judgements-2026-10-11.json: how many judged-correct links
are kept, how many judged-wrong ones survive, per status band. Prints the
table the issue asks for and writes it as JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import reranker  # noqa: E402
from linker import build_authority_lookup, link_voyagers_to_outremer  # noqa: E402

JUDGEMENTS = REPO_ROOT / "data" / "audits" / "linking-judgements-2026-10-11.json"


def documents() -> list[tuple[str, list[dict]]]:
    out = []
    for p in sorted((REPO_ROOT / "site" / "data").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("doc_id") == p.stem and d.get("source_file"):
            out.append((p.stem, d.get("persons") or []))
    return out


def score(links: list[dict], judged: dict[str, str | None], labels: dict[str, str]) -> dict:
    bands: Counter = Counter()
    kept_ok = kept_wrong = dropped_ok = unjudged = 0
    for lk in links:
        top = lk.get("top_candidate")
        if not top:
            if lk["person"] in judged and judged[lk["person"]] and lk.get("rerank", {}).get("veto"):
                dropped_ok += 1
            continue
        bands[lk["status"]] += 1
        if lk["person"] not in judged:
            unjudged += 1
            continue
        if judged[lk["person"]] == labels.get(top["outremer_id"]):
            kept_ok += 1
        else:
            kept_wrong += 1
    return {"bands": dict(bands), "links_correct": kept_ok, "links_wrong": kept_wrong,
            "correct_lost_to_veto": dropped_ok, "unjudged": unjudged}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--floor", type=float, default=None)
    ap.add_argument("--min-relevance", type=float, default=None)
    ap.add_argument("--output", type=Path, default=REPO_ROOT / "data" / "audits" / "rerank-report.json")
    args = ap.parse_args(argv)
    index = json.loads((REPO_ROOT / "scripts" / "outremer_index.json").read_text(encoding="utf-8"))
    lookup = build_authority_lookup(index)
    labels = {p["authority_id"]: p["preferred_label"] for p in index["persons"]}
    judged = json.loads(JUDGEMENTS.read_text(encoding="utf-8"))["mentions"]
    conf = reranker.settings()
    if args.min_relevance is not None:
        conf["min_relevance"] = args.min_relevance
    kwargs = {"min_score": args.floor} if args.floor is not None else {}

    fuzzy_links, veto_links = [], []
    summaries = []
    for doc_id, persons in documents():
        base = link_voyagers_to_outremer(persons, lookup, rerank=False, **kwargs)
        fuzzy_links += base
        with_veto = link_voyagers_to_outremer(persons, lookup, rerank=False, **kwargs)
        records = {e["authority_id"]: e["record"] for e in lookup if e.get("record")}
        summaries.append({"doc_id": doc_id, **reranker.apply_veto(with_veto, persons, records, conf=conf)})
        veto_links += with_veto

    report = {
        "floor": kwargs.get("min_score", "config"), "min_relevance": conf["min_relevance"], "model": conf["model"],
        "fuzzy": score(fuzzy_links, judged, labels), "with_veto": score(veto_links, judged, labels),
        "per_document": summaries,
        "vetoed": [{"doc": s["doc_id"]} for s in summaries if False],
    }
    report["vetoed_mentions"] = [
        {"person": lk["person"], "fuzzy_top": labels.get(lk["candidates"][0]["outremer_id"]),
         "fuzzy_score": lk["candidates"][0]["score"], "relevance": lk["rerank"]["top_relevance"],
         "judged": judged.get(lk["person"], "unjudged")}
        for lk in veto_links if lk.get("rerank", {}).get("veto")
    ]
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    f, v = report["fuzzy"], report["with_veto"]
    print(f"floor {report['floor']}  min_relevance {conf['min_relevance']}  model {conf['model']}")
    print(f"{'':<14}{'links':>7}{'correct':>9}{'wrong':>7}{'lost':>6}  bands")
    print(f"{'fuzzy only':<14}{sum(f['bands'].values()):>7}{f['links_correct']:>9}{f['links_wrong']:>7}{'-':>6}  {f['bands']}")
    print(f"{'with veto':<14}{sum(v['bands'].values()):>7}{v['links_correct']:>9}{v['links_wrong']:>7}{v['correct_lost_to_veto']:>6}  {v['bands']}")
    print(f"errors: {sum(s['errors'] for s in summaries)}  checked: {sum(s['checked'] for s in summaries)}  vetoed: {sum(s['vetoed'] for s in summaries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
