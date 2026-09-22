"""Bridge to production pipeline modules (scripts/ is not a package).

Single place where evaluation code reaches into scripts/: keeps the
sys.path shim out of every module and guarantees eval and production
share one matching implementation (the linker).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import linker  # noqa: E402  (needs the path shim above)


def load_authority_lookup() -> list[dict]:
    index = json.loads((_SCRIPTS / "outremer_index.json").read_text())
    return linker.build_authority_lookup(index)


def relink(persons: list[str], authority_lookup: list[dict], **kwargs) -> list[dict]:
    """Run the *current* linker over extracted person names.

    This is the measurement instrument for linker changes (M10.1–M10.3):
    extraction snapshots stay fixed, links are recomputed with the code
    under test — no LLM required.
    """
    person_dicts = [{"name": n} for n in persons if n]
    return linker.link_voyagers_to_outremer(person_dicts, authority_lookup, **kwargs)


# --- Recognition (M14.5, #124) -----------------------------------------------


def page_image(pdf: Path) -> bytes:
    """First page's embedded image, exactly as the production VLM path sends it."""
    import base64

    import run_pipeline

    urls = run_pipeline._page_images_as_data_urls(pdf, max_pages=1)
    if not urls:
        raise ValueError(f"{pdf.name} carries no page image")
    return base64.b64decode(urls[0].split(",", 1)[1])


def vlm_ocr(pdf: Path) -> tuple[str, str]:
    """Production VLM recognition of an image-only PDF → (text, model id)."""
    import run_pipeline

    from config import QWEN3_VL_MODEL

    return run_pipeline._qwen3vl_ocr(pdf), QWEN3_VL_MODEL


def atr_client():
    """The production ATR gateway client (URL, key and timeout from config)."""
    from atr_client import AtrClient

    return AtrClient()


def recognise(pdf: Path) -> tuple[str, dict[str, int]]:
    """The production document reader on a scanned PDF → (text, engines used)."""
    import run_pipeline

    run_pipeline._recognition_engines_used.clear()
    text = run_pipeline.read_input(pdf)
    return text, dict(run_pipeline._recognition_engines_used)
