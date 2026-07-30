import json
import subprocess
from pathlib import Path

from scripts import run_pipeline

ROOT = Path(__file__).resolve().parents[1]


def test_evidence_core_indexes_passages_candidates_and_provenance():
    script = """
import {readFileSync} from 'node:fs';
import {buildEvidenceView, evidencePathForDocument} from './site/evidence-review-core.mjs';
const dataset = JSON.parse(readFileSync('./fixtures/evidence-first/representative.json'));
const view = buildEvidenceView(dataset);
console.log(JSON.stringify({
  path: evidencePathForDocument('doc one'),
  count: view.length,
  passage: view[0].passages[0].text,
  candidates: view.find(x => x.target.type === 'identity_hypothesis').candidates.length
}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    output = json.loads(result.stdout)
    assert output["path"] == "./evidence/doc%20one.evidence.json"
    assert output["count"] == 3
    assert "Baldwin" in output["passage"]
    assert output["candidates"] == 2


def test_explorer_and_compatibility_page_share_the_renderer():
    explorer = (ROOT / "site" / "explorer.html").read_text(encoding="utf-8")
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    compatibility = (ROOT / "site" / "evidence-review.js").read_text(encoding="utf-8")
    assert 'id="panel-evidence"' in explorer
    assert 'from "./evidence-review-core.mjs"' in app
    assert 'from "./evidence-review-core.mjs"' in compatibility
    assert "legacy review remains active" in app


def test_pipeline_mirrors_validated_evidence_into_site(monkeypatch, tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("Baldwin travelled.", encoding="utf-8")
    monkeypatch.setattr(
        run_pipeline,
        "extract_persons_and_metadata",
        lambda *args, **kwargs: {
            "persons": [{
                "name": "Baldwin",
                "raw_mention": "Baldwin",
                "context": "Baldwin travelled.",
                "source_offset": 0,
                "confidence": 0.8,
            }],
            "metadata": {"title": "Source"},
            "bibtex": "",
            "engine": {"provider": "test", "model": "fixture"},
        },
    )
    monkeypatch.setattr(run_pipeline, "link_voyagers_to_outremer", lambda *args: [])
    site = tmp_path / "site"
    evidence = tmp_path / "data" / "evidence"
    for directory in (site / "data", site / "bib", tmp_path / "bib", evidence):
        directory.mkdir(parents=True, exist_ok=True)
    result = run_pipeline.process_file(
        source,
        site_data_dir=site / "data",
        bib_dir=tmp_path / "bib",
        site_bib_dir=site / "bib",
        authority_lookup=[],
        use_llm_metadata=False,
        evidence_dir=evidence,
        site_evidence_dir=site / "evidence",
    )
    evidence_path = result[3]
    mirror = site / "evidence" / evidence_path.name
    assert mirror.read_bytes() == evidence_path.read_bytes()
