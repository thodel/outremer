"""Run one scanned page through several recognition engines and keep the evidence.

M14.5 (#124): the same page through the VLM path (GPUStack) and the ATR
gateway's ``/ocr`` (kraken, TrOCR), each transcript stored with its engine
provenance, plus the candidate distance between the engines. A measurement,
not a fusion — Epic 16 stays gated until recognition quality is measurable.

    python -m evaluation.recognition_compare PAGE.pdf \\
        --engine vlm \\
        --engine kraken:kraken-catmus_medieval \\
        --engine trocr:trocr-essoins-middle-latin \\
        --out evaluation/recognition/<name>

Writes one ``<engine>.txt`` per engine and ``provenance.json``. Needs the
university network (GPUStack and the ATR gateway are not reachable outside).
Exit status 1 if any engine failed; what did run is written regardless.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from evaluation import _pipeline
from evaluation.metrics import candidate_distance, cer

# kraken's blla scales every input to a fixed height, so its cost follows the
# aspect ratio, not the pixel count: the same content took 5.8 s page-shaped
# and ~290 s as a line strip, and the strip's GPU memory is not given back
# (one starved party into CUDA OOM on the shared serving box). Strips — such
# as the hi-res incipit fixture, 4680×820 — go to the VLM path only.
MAX_ATR_ASPECT = 2.5

DISTANCE_NOTE = (
    "Candidate distance measures disagreement between engines, not accuracy: "
    "symmetric edit distance over the longer normalised transcript."
)


def _slug(spec: str) -> str:
    return spec.replace(":", "__").replace("/", "_")


def _dimensions(image: bytes) -> tuple[int, int]:
    from PIL import Image

    return Image.open(io.BytesIO(image)).size


def _run(spec: str, pdf: Path, image: bytes) -> tuple[str, dict]:
    started = time.monotonic()
    if spec == "vlm":
        text, model = _pipeline.vlm_ocr(pdf)
        record = {"engine": "vlm", "backend": "gpustack", "model": model}
    else:
        engine, _, model = spec.partition(":")
        with _pipeline.atr_client() as client:
            result = client.transcribe(image, model=model, engine=engine)
        text = result.text
        record = {
            "engine": result.engine,
            "backend": "atr-gateway",
            "model": result.model,
            "service_version": result.service_version,
            "confidence": result.confidence,
        }
    record["seconds"] = round(time.monotonic() - started, 1)
    record["chars"] = len(text.strip())
    return text, record


def compare(
    pdf: Path,
    engines: list[str],
    out: Path,
    *,
    reference: Path | None = None,
) -> dict:
    """Run *engines* over the first page of *pdf*; write transcripts + provenance."""
    for spec in engines:
        if spec != "vlm" and ":" not in spec:
            raise ValueError(f"engine {spec!r}: use 'vlm' or '<engine>:<model-id>'")

    image = _pipeline.page_image(pdf)
    width, height = _dimensions(image)
    aspect = max(width, height) / min(width, height)
    if aspect > MAX_ATR_ASPECT and any(spec != "vlm" for spec in engines):
        raise ValueError(
            f"{pdf.name} is {width}×{height} (aspect {aspect:.1f}): a strip, not "
            f"a page. kraken's segmenter scales to a fixed height, so strips "
            f"cost ~50× and hold GPU memory on the shared gateway — send it to "
            f"the VLM path only, or crop a page-shaped region (≤ {MAX_ATR_ASPECT}:1)."
        )

    out.mkdir(parents=True, exist_ok=True)
    transcripts: dict[str, str] = {}
    records: list[dict] = []
    for spec in engines:
        try:
            text, record = _run(spec, pdf, image)
        except Exception as exc:  # noqa: BLE001 — record, keep measuring the rest
            records.append({"spec": spec, "error": f"{type(exc).__name__}: {exc}"})
            continue
        record["spec"] = spec
        record["file"] = f"{_slug(spec)}.txt"
        if not text.strip():
            record["error"] = "empty transcription"
        (out / record["file"]).write_text(text, encoding="utf-8")
        transcripts[spec] = text
        records.append(record)

    usable = {spec: text for spec, text in transcripts.items() if text.strip()}
    specs = sorted(usable)
    pairwise = [
        {
            "a": a,
            "b": b,
            "distance": round(candidate_distance([usable[a], usable[b]])["mean_cer"], 3),
        }
        for i, a in enumerate(specs)
        for b in specs[i + 1:]
    ]
    provenance = {
        "measurement": "M14.5 recognition comparison (#124)",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": {
            "file": pdf.name,
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "page_image": {"width": width, "height": height},
        },
        "engines": records,
        "candidate_distance": {"note": DISTANCE_NOTE, "pairwise": pairwise},
    }
    if reference is not None:
        # Absolute CER only against an independent edition, never against a
        # Human-in-the-Loop selection (see evaluation/README.md).
        ref = reference.read_text(encoding="utf-8")
        provenance["reference"] = {
            "file": reference.name,
            "cer": {spec: round(cer(ref, text), 3) for spec, text in usable.items()},
        }
    (out / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return provenance


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pdf", type=Path, help="image-only PDF; its first page is used")
    ap.add_argument(
        "--engine", action="append", required=True, dest="engines",
        help="'vlm' or '<kraken|trocr>:<model-id>'; repeat for each engine",
    )
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument(
        "--reference", type=Path,
        help="independent edition of exactly this page (enables absolute CER)",
    )
    args = ap.parse_args(argv)
    try:
        provenance = compare(args.pdf, args.engines, args.out, reference=args.reference)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    for record in provenance["engines"]:
        status = record.get("error") or f"{record['chars']} chars in {record['seconds']} s"
        print(f"{record['spec']:<40} {status}")
    for pair in provenance["candidate_distance"]["pairwise"]:
        print(f"distance {pair['a']} ↔ {pair['b']}: {pair['distance']}")
    return 1 if any("error" in record for record in provenance["engines"]) else 0


if __name__ == "__main__":
    sys.exit(main())
