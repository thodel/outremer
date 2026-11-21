"""Ensemble recognition: one page, several attributed candidates (M16.1, #79).

Epic 16's first milestone (#66): page-level VLM + best kraken + best TrOCR
through the ATR gateway, adding further candidates while they disagree. The
dials ``ENSEMBLE_MAX_LOOPS``/``ENSEMBLE_PER_ENGINE`` steer coverage and cost,
not quality: every added candidate is one real GPU inference (~30–60 s per
model per page). The output is a pool of **competing claims**, each candidate
persisted with engine and model provenance; nothing here asserts that the
text is X (fusion is M16.2–M16.3, a separate gated step).

    python -m evaluation.ensemble PAGE.pdf --out evaluation/recognition/<name>

Needs the university network, like recognition_compare; exit status 1 if any
candidate failed, what did run is written regardless.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from evaluation import _pipeline
from evaluation.metrics import candidate_distance
from evaluation.recognition_compare import MAX_ATR_ASPECT, _dimensions, _slug

#: Base set in priority order; the loop draws growth candidates from the gateway families.
FAMILIES = ("vlm", "kraken", "trocr")
GATEWAY_FAMILIES = ("kraken", "trocr")

CLAIMS_NOTE = (
    "Every candidate is a competing claim about this page, attributed to the "
    "engine and model that produced it. None asserts the text is X: fusion is "
    "a separate, gated step (M16.2–M16.3, #66)."
)


def build_pools(client, *, model_order: dict[str, tuple[str, ...]] | None = None,
                per_engine: int) -> dict[str, list[str]]:
    """Per-family pools: curated order first, the registry fills the depth."""
    import config

    order = config.ENSEMBLE_MODEL_ORDER if model_order is None else model_order
    registry = client.list_models()
    pools: dict[str, list[str]] = {}
    for family in GATEWAY_FAMILIES:
        ranked = [m for m in order.get(family, ()) if any(e["id"] == m for e in registry)]
        extra = [e["id"] for e in registry if e.get("engine") == family and e["id"] not in ranked]
        pools[family] = (ranked + extra)[:per_engine]
    return pools


def disagreement(texts: list[str]) -> float:
    """The pool's disagreement: max pairwise candidate distance (0.0 for <2)."""
    if len(texts) < 2:
        return 0.0
    return candidate_distance(texts)["max_cer"]


def _usable(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if "error" not in c and c.get("chars")]


def _next_family(pools, used, last=None):
    """The next family to draw from, alternating where both have entries."""
    eligible = [f for f in GATEWAY_FAMILIES if len(pools.get(f, ())) > len(used[f])]
    if not eligible:
        return None
    if last is not None:
        for family in eligible:
            if family != last:
                return family
    return eligible[0]


def run_ensemble(pdf: Path, out: Path, *, min_engines=None, max_loops=None,
                 per_engine=None, agree_cer=None, model_order=None,
                 client=None, vlm=None) -> dict:  # noqa: E501
    """Run the ensemble over the first page of *pdf*; persist the pool.

    ``client``/``vlm`` default to the ``_pipeline`` bridges; tests inject fakes.
    """
    import config

    min_engines = config.ENSEMBLE_MIN_ENGINES if min_engines is None else min_engines
    max_loops = config.ENSEMBLE_MAX_LOOPS if max_loops is None else max_loops
    per_engine = config.ENSEMBLE_PER_ENGINE if per_engine is None else per_engine
    agree_cer = config.ENSEMBLE_AGREEMENT_CER if agree_cer is None else agree_cer
    if not 1 <= min_engines <= len(FAMILIES):
        raise ValueError(f"min_engines must be 1..{len(FAMILIES)}, got {min_engines}")
    if max_loops < 0 or per_engine < 1:
        raise ValueError(f"max_loops >= 0, per_engine >= 1, got {max_loops}/{per_engine}")

    base_families = FAMILIES[:min_engines]
    vlm = _pipeline.vlm_ocr if vlm is None else vlm
    client = _pipeline.atr_client() if client is None else client

    image = _pipeline.page_image(pdf)
    width, height = _dimensions(image)
    aspect = max(width, height) / min(width, height)
    if aspect > MAX_ATR_ASPECT and any(f in GATEWAY_FAMILIES for f in base_families):
        raise ValueError(f"{pdf.name} is {width}×{height} (aspect {aspect:.1f}): a "
                         "strip, not a page — the models are page-trained; run the VLM "
                         "alone (min_engines=1) or crop to a page first")
    pools = build_pools(client, model_order=model_order, per_engine=per_engine) \
        if set(base_families) & set(GATEWAY_FAMILIES) else {}

    out.mkdir(parents=True, exist_ok=True)
    candidates: list[dict] = []
    used: dict[str, set[str]] = {f: set() for f in GATEWAY_FAMILIES}

    def add_candidate(family: str, model: str | None, round_no: int) -> dict:
        record: dict = {"family": family, "round": round_no}
        started = time.monotonic()
        try:
            if family == "vlm":
                record["spec"] = "vlm"
                text, model_id = vlm(pdf)
                record.update(engine="vlm", backend="gpustack", model=model_id)
            else:
                record["spec"] = f"{family}:{model}"
                with client as c:
                    result = c.transcribe(image, model=model, engine=family)
                    entry = next((m for m in c.list_models() if m.get("id") == model), {})
                record.update(
                    engine=result.engine or family, backend="atr-gateway",
                    model=result.model, service_version=result.service_version,
                    confidence=result.confidence,
                    weights={k: entry[k] for k in ("zenodo_id", "hf_repo") if entry.get(k)},
                )
                text = result.text
            record["text"] = text
            record["seconds"] = round(time.monotonic() - started, 1)
            record["chars"] = len(text.strip())
            if not text.strip():
                record["error"] = "empty transcription"
            else:
                record["file"] = f"{_slug(record['spec'])}.txt"
                (out / record["file"]).write_text(text, encoding="utf-8")
        except Exception as exc:  # record the failure; keep the pool growing
            record["error"] = f"{type(exc).__name__}: {exc}"
        candidates.append(record)
        if model is not None and family in used:
            used[family].add(model)
        return record

    for family in base_families:
        if family == "vlm":
            add_candidate(family, None, 1)
        elif pools.get(family):
            add_candidate(family, pools[family][0], 1)
        else:
            candidates.append({"family": family, "round": 1, "spec": family,
                               "error": "no models for this engine in the gateway registry"})

    loop_log: list[dict] = []
    stop_reason = "max_loops"
    last_family: str | None = None
    for round_no in range(2, 2 + max_loops):
        usable = _usable(candidates)
        if len(usable) < 2:
            stop_reason = "insufficient_candidates"
            break
        before = disagreement([c["text"] for c in usable])
        if before <= agree_cer:
            stop_reason = "agreement"
            break
        family = _next_family(pools, used, last=last_family)
        if family is None:
            stop_reason = "pools_exhausted"
            break
        last_family = family
        record = add_candidate(family, pools[family][len(used[family])], round_no)
        usable_after = _usable(candidates)
        after = [c["text"] for c in usable_after]
        loop_log.append({
            "round": round_no, "disagreement_before": round(before, 3),
            "added": record.get("spec", family), "failed": "error" in record,
            "disagreement_after": round(disagreement(after), 3)
            if len(usable_after) >= 2 else None,
        })

    usable = _usable(candidates)
    provenance: dict = {
        "measurement": "M16.1 ensemble recognition (#79)",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": {"file": pdf.name,
                  "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                  "page_image": {"width": width, "height": height}},
        "status": "competing_claims",
        "claims_note": CLAIMS_NOTE,
        "policy": {"min_engines": min_engines, "max_loops": max_loops,
                   "per_engine": per_engine, "agreement_cer": agree_cer,
                   "pools": pools},
        "candidates": candidates,
        "loop_log": loop_log,
        "stopping": {
            "reason": stop_reason,
            "disagreement": round(candidate_distance([c["text"] for c in usable])["max_cer"], 3),
        },
    }
    (out / "provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return provenance


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pdf", type=Path, help="image-only PDF; its first page is used")
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument("--min-engines", type=int, choices=range(1, 4), default=None)
    ap.add_argument("--max-loops", type=int, default=None)
    ap.add_argument("--per-engine", type=int, default=None)
    args = ap.parse_args(argv)
    try:
        prov = run_ensemble(args.pdf, args.out, min_engines=args.min_engines,
                            max_loops=args.max_loops, per_engine=args.per_engine)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    for c in prov["candidates"]:
        status = c.get("error") or f"{c['chars']} chars in {c.get('seconds', '?')} s"
        print(f"round {c['round']}  {c.get('spec', c['family']):<40} {status}")
    print(f"stopped: {prov['stopping']['reason']} (max-pairwise CER {prov['stopping']['disagreement']})")
    return 1 if any("error" in c for c in prov["candidates"]) else 0


if __name__ == "__main__":
    sys.exit(main())
