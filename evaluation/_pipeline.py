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
