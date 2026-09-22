"""Live OCR canary: does scanned-page recognition still read the hi-res fixture?

Every nightly document has a text layer, so production never exercises
recognition. From 2026-09-07 to 2026-09-22 it returned empty text while every
nightly stayed green (#142). ``deploy/tei/healthcheck.sh`` runs this weekly;
the ``OUTREMER_LIVE_OCR`` test applies the same judgement.

    python -m evaluation.ocr_canary      # one JSON line; exit 0 = pass

Pass means the output attests this charter's vocabulary: at least eight
distinct output words match words of the published edition — allowing medieval
abbreviation by suspension ("Episc." for episcopis) and inflection (comites ~
comitibus) — and more than twice as many as match an unrelated English control.
Distinct words, because the first version compared CER against the edition and
against a control five times shorter, and CER divides by the reference length:
any long output looked "closer to the charter", including the control text
repeated. Repetition adds no distinct words, so a runaway loop cannot pass by
volume. Measured on the real output (2026-09-22): 14 attested words, 0 for
the control — the same 14 with its 12 000-character loop removed; the strongest
negative, a generic Latin formula from another charter, 4.

Runs the production reader and needs no dev dependencies: the tei venv is
installed from the lockfile and has no pytest. Needs GPUStack, i.e. a host
inside the university network.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from evaluation import _pipeline

SCANS = _pipeline.REPO_ROOT / "tests" / "fixtures" / "scans"
FIXTURE = SCANS / "magna-carta-1215-incipit-hires.pdf"
REFERENCE = SCANS / "magna-carta-1215-incipit.reference.txt"
# Unrelated control: modern English scholarly prose, same order of magnitude.
CONTROL = (
    "The Popes and the Crusades. The First Crusade was the work of Pope Urban "
    "the Second, and the movement remained under papal direction throughout "
    "the twelfth and thirteenth centuries, as the letters of the popes show."
)
MIN_WORD = 4  # shorter tokens match by accident too often
MIN_ATTESTED = 8


def _words(text: str) -> set[str]:
    """Letter-only word types, case- and diacritic-folded, u/v and i/j merged."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.replace("v", "u").replace("j", "i")
    return {w for w in re.findall(r"[^\W\d_]+", folded) if len(w) >= MIN_WORD}


def _attests(word: str, vocable: str) -> bool:
    if word.startswith(vocable) or vocable.startswith(word):  # suspension
        return min(len(word), len(vocable)) >= MIN_WORD
    shared = 0
    for a, b in zip(word, vocable):
        if a != b:
            break
        shared += 1
    return shared >= 5  # inflection


def _attested(text: str, vocabulary: str) -> list[str]:
    vocables = _words(vocabulary)
    return sorted(w for w in _words(text) if any(_attests(w, v) for v in vocables))


def judge(text: str, reference: str) -> dict:
    """Does *text* attest this charter's vocabulary, rather than noise or prose?"""
    charter = _attested(text, reference)
    control = _attested(text, CONTROL)
    tokens = text.split()
    top = Counter(tokens).most_common(1)
    return {
        "ok": len(charter) >= MIN_ATTESTED and len(charter) > 2 * len(control),
        "chars": len(text.strip()),
        "charter_words": len(charter),
        "control_words": len(control),
        # Informational: share of the single most frequent token — a runaway
        # repetition loop (#73) shows up here without failing the canary.
        "repeat_share": round(top[0][1] / len(tokens), 3) if tokens else 0.0,
        "attested": charter[:20],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--save", type=Path, help="also write the transcription here")
    args = ap.parse_args(argv)
    text, engines = _pipeline.recognise(FIXTURE)
    if args.save:
        args.save.write_text(text, encoding="utf-8")
    verdict = judge(text, REFERENCE.read_text(encoding="utf-8"))
    ok = verdict.pop("ok")
    print(json.dumps(
        {"canary": "pass" if ok else "fail", "engines": engines, **verdict},
        ensure_ascii=False,
    ))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
