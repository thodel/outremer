"""#161 — a document's id is its source, not its text state."""

import json
from pathlib import Path

from scripts import run_pipeline
from scripts.migrate_doc_ids import HASHED, migrate, stable_id

REPO = Path(__file__).resolve().parent.parent


def test_document_id_is_the_source_slug_without_a_hash():
    assert run_pipeline.document_id(Path("data/raw/Hamblin-MuslimPerspectivesMilitary-2001.pdf")) \
        == "hamblin-muslimperspectivesmilitary-2001"
    assert not HASHED.match(run_pipeline.document_id(Path("x/RileySmith-Motives-1983.pdf")))


def test_every_adjudication_points_at_an_indexed_document():
    """The guard: an orphaned decision is a red test, not a silent loss."""
    index = json.loads((REPO / "site" / "index.json").read_text(encoding="utf-8"))
    current = {Path(n).stem for n in index["documents"]}
    decisions = json.loads((REPO / "data" / "decisions.json").read_text(encoding="utf-8"))
    orphaned = sorted({d["doc_id"] for d in decisions if d["doc_id"] not in current})
    assert orphaned == [], orphaned
    assert all(not HASHED.match(d["doc_id"]) for d in decisions)


def test_fixtures_are_named_after_current_documents():
    index = json.loads((REPO / "site" / "index.json").read_text(encoding="utf-8"))
    current = {Path(n).stem for n in index["documents"]}
    for fx in (REPO / "evaluation" / "fixtures").glob("*.json"):
        assert fx.stem in current, fx.name
        assert json.loads(fx.read_text(encoding="utf-8"))["doc_id"] == fx.stem


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _doc(doc_id: str, source: str, run_at: str) -> dict:
    return {"doc_id": doc_id, "source_file": source, "run_at": run_at,
            "text_sha256": "0" * 64, "metadata": {"title": "T"}, "language_hint": None,
            "persons": [{"name": "Godfrey of Bouillon", "context": "x", "confidence": 0.9}],
            "links": [], "extraction_engine": {"provider": "gpustack", "model": "m"}}


def test_migration_moves_everything_to_the_stable_id(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "data" / "raw").mkdir(parents=True)
    (repo / "data" / "raw" / "H.pdf").write_bytes(b"%PDF")
    src = "data/raw/H.pdf"
    _write(repo / "site/data/h-aaaaaaaaaaaa.json", _doc("h-aaaaaaaaaaaa", src, "2026-08-29T00:00:00+00:00"))
    _write(repo / "site/data/h-bbbbbbbbbbbb.json", _doc("h-bbbbbbbbbbbb", src, "2026-10-03T00:00:00+00:00"))
    _write(repo / "site/data/status.json", {"run": {}})
    _write(repo / "site/data/wikidata_matches.json",
           {"status": {}, "h-aaaaaaaaaaaa": {"x": 1}, "h-bbbbbbbbbbbb": {"y": 2}, "fmg": {"z": 3}})
    for d in ("bib", "site/bib"):
        (repo / d).mkdir(parents=True, exist_ok=True)
        (repo / d / "h-aaaaaaaaaaaa.bib").write_text("old")
        (repo / d / "h-bbbbbbbbbbbb.bib").write_text("new")
    _write(repo / "data/decisions.json", [
        {"doc_id": "h-aaaaaaaaaaaa", "person": "Godfrey of Bouillon", "outremer_id": "AUTH:CR184",
         "decision": "accept", "client_id": "a", "submitted_at": "2026-02-28T00:00:00"},
        {"doc_id": "other-cccccccccccc", "person": "P", "outremer_id": "AUTH:CR1", "decision": "reject"},
    ])
    _write(repo / "evaluation/fixtures/h-aaaaaaaaaaaa.json",
           {"doc_id": "h-aaaaaaaaaaaa", "mode": "adjudicated", "accepted": [], "rejected": []})
    monkeypatch.chdir(repo)

    plan = migrate(repo)

    assert plan["aliases"] == {"h-aaaaaaaaaaaa": "h", "h-bbbbbbbbbbbb": "h"}
    assert plan["superseded"] == ["h-aaaaaaaaaaaa"]
    data_dir = repo / "site" / "data"
    assert sorted(p.name for p in data_dir.glob("h*.json")) == ["h.json"]
    doc = json.loads((data_dir / "h.json").read_text())
    assert doc["doc_id"] == "h" and doc["migrated_from"] == "h-bbbbbbbbbbbb"
    assert (repo / "bib" / "h.bib").read_text() == "new"
    assert not (repo / "bib" / "h-aaaaaaaaaaaa.bib").exists()
    assert (repo / "data" / "evidence" / "h.evidence.json").exists()
    assert (repo / "site" / "evidence" / "h.evidence.json").exists()
    decisions = json.loads((repo / "data/decisions.json").read_text())
    assert decisions[0]["doc_id"] == "h" and decisions[0]["migrated_from"] == "h-aaaaaaaaaaaa"
    assert decisions[1]["doc_id"] == "other-cccccccccccc", "no document for it: left alone, the guard reports it"
    fx = json.loads((repo / "evaluation/fixtures/h.json").read_text())
    assert fx["doc_id"] == "h" and fx["migrated_from"] == "h-aaaaaaaaaaaa"
    wm = json.loads((data_dir / "wikidata_matches.json").read_text())
    assert wm == {"status": {}, "h": {"y": 2}}
    aliases = json.loads((repo / "data/doc_id_aliases.json").read_text())["aliases"]
    assert aliases == {"h-aaaaaaaaaaaa": "h", "h-bbbbbbbbbbbb": "h"}
    index = json.loads((repo / "site/index.json").read_text())
    assert index["documents"] == ["h.json"] and index["aliases"] == aliases


def test_stable_id_leaves_unhashed_ids_alone():
    assert stable_id("munro-popescrusades-1916-28b5e7f7d267") == "munro-popescrusades-1916"
    assert stable_id("munro-popescrusades-1916") == "munro-popescrusades-1916"
    assert stable_id("fmg_medlands_crusaders") == "fmg_medlands_crusaders"
