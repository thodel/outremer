"""#152 — site/index.json names the current documents, one per source."""

import json
import os
import time

from scripts.run_pipeline import build_site_index


def _doc(path, doc_id, source, persons=1, run_at=None, **extra):
    data = {"doc_id": doc_id, "source_file": source,
            "persons": [{"name": "X"}] * persons, "links": [], **extra}
    if run_at:
        data["run_at"] = run_at
    path.write_text(json.dumps(data))


def test_only_pipeline_documents_are_listed(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _doc(data / "a-111.json", "a-111", "data/raw/A.pdf")
    (data / "status.json").write_text(json.dumps({"run": {}, "gate": {}}))
    (data / "authority.json").write_text(json.dumps({"persons": []}))
    (data / "wikidata_matches.json").write_text(json.dumps({"a-111": {}}))
    # a hand-made export: has a doc_id but names no source and holds no link
    (data / "fmg.json").write_text(json.dumps({"doc_id": "fmg", "persons": []}))
    # a pipeline-shaped file whose doc_id is not its name
    _doc(data / "filtered-a.json", "a-111", "data/raw/A.pdf")

    index = build_site_index(data, tmp_path)

    assert index["documents"] == ["a-111.json"]
    assert index["count"] == 1
    assert index["excluded"] == {
        "authority.json": "doc_id does not match the file name",
        "filtered-a.json": "doc_id does not match the file name",
        "fmg.json": "no source_file",
        "status.json": "doc_id does not match the file name",
        "wikidata_matches.json": "doc_id does not match the file name",
    }
    assert json.loads((tmp_path / "index.json").read_text())["documents"] == ["a-111.json"]


def test_same_source_twice_lists_only_the_latest_run(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _doc(data / "h-old.json", "h-old", "data/raw/H.pdf", run_at="2026-08-29T03:00:00+00:00")
    _doc(data / "h-new.json", "h-new", "data/raw/H.pdf", run_at="2026-10-03T03:00:00+00:00")
    _doc(data / "m-1.json", "m-1", "data/raw/M.pdf", run_at="2026-10-03T03:00:00+00:00")

    index = build_site_index(data, tmp_path)

    assert index["documents"] == ["h-new.json", "m-1.json"]
    assert index["superseded"] == {"h-old.json": "h-new.json"}


def test_without_run_at_the_newer_file_wins(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _doc(data / "h-aaa.json", "h-aaa", "data/raw/H.pdf")
    _doc(data / "h-bbb.json", "h-bbb", "data/raw/H.pdf")
    old = time.time() - 3600
    os.utime(data / "h-aaa.json", (old, old))

    index = build_site_index(data, tmp_path)

    assert index["documents"] == ["h-bbb.json"]
    assert index["superseded"] == {"h-aaa.json": "h-bbb.json"}


def test_a_document_without_persons_is_not_listed(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _doc(data / "e-1.json", "e-1", "data/raw/E.pdf", persons=0)
    index = build_site_index(data, tmp_path)
    assert index["documents"] == []
    assert index["excluded"] == {"e-1.json": "no persons"}
