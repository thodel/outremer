"""Evaluation harness for the OUTREMER pipeline.

Measures extraction (person mentions) and linking (authority matches)
against gold fixtures, so prompt/model changes are judged by numbers
rather than impressions. Pattern adapted from agentic_historian's
eval harness.

Run from repo root:
    python -m evaluation.harness --fixtures evaluation/fixtures
"""

from evaluation.metrics import extraction_prf, linking_agreement  # noqa: F401
