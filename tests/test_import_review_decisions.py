"""M13.3 (#179): the nightly carries review-API events into data/decisions.json.

Real HTTP over loopback against scripts/review_api.py, then the importer,
then the fixture builder — the whole round trip except the browser.
"""

import json
import threading
from http.server import ThreadingHTTPServer

import import_review_decisions as imp
import pytest
from review_api import ReviewStore, make_handler

from evaluation.build_fixture import build_fixtures

PAIR = {"doc_id": "doc1", "person": "Hugh of Payns", "outremer_id": "AUTH:CR7"}


@pytest.fixture()
def api(tmp_path):
    store = ReviewStore(str(tmp_path / "r.db"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, None, None))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", store
    srv.shutdown()


@pytest.fixture()
def decisions(tmp_path):
    p = tmp_path / "decisions.json"
    p.write_text(json.dumps([{**PAIR, "decision": "reject", "client_id": "anon-old",
                              "submitted_at": "2026-02-22T20:07:38"}]))
    return p


def _run(url, path, *extra):
    return imp.main(["--url", url, "--decisions", str(path), *extra])


def test_new_events_are_appended_with_their_provenance(api, decisions, capsys):
    url, store = api
    store.append({**PAIR, "decision": "accept", "client_id": "rev-a", "scholar_name": "A. B."})
    assert _run(url, decisions) == 0
    rows = json.loads(decisions.read_text())
    assert len(rows) == 2
    new = rows[1]
    assert new["decision"] == "accept" and new["scholar_name"] == "A. B."
    assert new["client_id"] == "rev-a" and new["submitted_at"] and new["source"] == "review_api"
    assert "id" not in new and "supersedes" not in new
    out = capsys.readouterr().out
    assert "1 new decision(s): 1 accept — from A. B. (1)" in out
    assert "wrote" in out


def test_a_second_run_imports_nothing_and_the_file_is_byte_identical(api, decisions, capsys):
    url, store = api
    store.append({**PAIR, "decision": "accept", "client_id": "rev-a"})
    _run(url, decisions)
    before = decisions.read_bytes()
    assert _run(url, decisions) == 0
    assert decisions.read_bytes() == before
    assert "nothing new" in capsys.readouterr().out


def test_the_file_is_append_only(api, decisions):
    url, store = api
    store.append({**PAIR, "decision": "accept", "client_id": "rev-a"})
    _run(url, decisions)
    rows = json.loads(decisions.read_text())
    assert rows[0]["client_id"] == "anon-old" and rows[0]["decision"] == "reject"


def test_a_withdrawal_takes_only_that_reviewers_vote_out_of_the_gold(api, decisions, tmp_path):
    url, store = api
    store.append({**PAIR, "decision": "accept", "client_id": "rev-a"})
    store.append({**PAIR, "decision": "accept", "client_id": "rev-b"})
    _run(url, decisions)
    # one reviewer withdraws: the API appends "unresolved" by rev-a
    store.withdraw({**PAIR, "client_id": "rev-a"})
    _run(url, decisions)
    rows = json.loads(decisions.read_text())
    assert [r["decision"] for r in rows] == ["reject", "accept", "accept", "unresolved"]
    fx = build_fixtures(decisions, tmp_path)   # no site data: gold only
    # anon-old reject (-1) + rev-b accept (+1) = tie → dropped; rev-a no longer counts
    assert fx == []                                   # tie: the pair is in no gold
    store.withdraw({**PAIR, "client_id": "rev-b"})
    _run(url, decisions)
    fx = build_fixtures(decisions, tmp_path)
    assert fx[0]["rejected"] == [["Hugh of Payns", "AUTH:CR7"]]   # the old reject stands alone


def test_validation_failure_leaves_the_file_untouched(api, decisions, capsys):
    url, store = api
    # the API refuses bad decisions, so corrupt the stored row directly
    store.append({**PAIR, "decision": "accept", "client_id": "rev-a"})
    store._conn.execute("UPDATE decision_events SET decision='maybe'")
    store._conn.commit()
    before = decisions.read_bytes()
    assert _run(url, decisions) == 1
    assert decisions.read_bytes() == before
    assert "left unchanged" in capsys.readouterr().err
    assert not list(decisions.parent.glob("tmp*"))


def test_dry_run_reports_but_writes_nothing(api, decisions, capsys):
    url, store = api
    store.append({**PAIR, "decision": "accept", "client_id": "rev-a"})
    before = decisions.read_bytes()
    assert _run(url, decisions, "--dry-run") == 0
    assert decisions.read_bytes() == before
    assert "dry run" in capsys.readouterr().out


def test_unreachable_api_is_exit_1_not_an_empty_import(decisions, capsys):
    before = decisions.read_bytes()
    assert _run("http://127.0.0.1:9", decisions) == 1
    assert decisions.read_bytes() == before
    assert "unreachable" in capsys.readouterr().err


def test_since_is_the_newest_imported_stamp_only(api, decisions):
    """Hand-made records in the file (no source) never narrow the window."""
    url, store = api
    rows = json.loads(decisions.read_text())
    rows.append({**PAIR, "person": "Later", "decision": "accept", "client_id": "hand",
                 "submitted_at": "2099-01-01T00:00:00"})
    decisions.write_text(json.dumps(rows))
    store.append({**PAIR, "decision": "accept", "client_id": "rev-a"})
    assert _run(url, decisions) == 0
    assert len(json.loads(decisions.read_text())) == 3
