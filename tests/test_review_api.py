"""Tests for scripts/review_api.py (#114 v1) — real HTTP over loopback."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from review_api import ReviewStore, make_handler


@pytest.fixture()
def api(tmp_path):
    store = ReviewStore(str(tmp_path / "r.db"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, "sekrit", "https://thodel.github.io"))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base
    srv.shutdown()


def _req(url, data=None, headers=None, method=None):
    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(r, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def test_health(api):
    code, body = _req(api + "/health")
    assert code == 200 and body["status"] == "ok" and body["events"] == 0


def test_post_requires_token(api):
    ev = json.dumps({"doc_id": "d", "person": "Godfrey", "decision": "accept"}).encode()
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(api + "/decisions", data=ev, headers={"Content-Type": "application/json"})
    assert e.value.code == 401


def test_append_only_latest_event_wins(api):
    h = {"Content-Type": "application/json", "X-Review-Token": "sekrit"}
    for decision in ("accept", "reject"):
        ev = json.dumps({"doc_id": "d1", "person": "Godfrey  of\nBouillon",
                         "outremer_id": "AUTH:CR184", "decision": decision,
                         "client_id": "rev-a"}).encode()
        code, _ = _req(api + "/decisions", data=ev, headers=h)
        assert code == 201
    code, current = _req(api + "/decisions?doc_id=d1")
    assert len(current) == 1
    assert current[0]["decision"] == "reject"          # latest event wins
    assert current[0]["person"] == "Godfrey of Bouillon"  # whitespace collapsed
    code, body = _req(api + "/health")
    assert body["events"] == 2                          # audit trail keeps both


def test_export_is_pipeline_compatible(api, tmp_path):
    h = {"Content-Type": "application/json", "X-Review-Token": "sekrit"}
    ev = json.dumps({"doc_id": "d1", "person": "Tancred", "outremer_id": "AUTH:CR86",
                     "decision": "accept", "client_id": "rev-b"}).encode()
    _req(api + "/decisions", data=ev, headers=h)
    _, export = _req(api + "/export")
    # exactly the shape validate_decisions_file ingests
    from validate_decisions import validate_decisions_file
    p = tmp_path / "decisions.json"
    p.write_text(json.dumps(export))
    result = validate_decisions_file(p)
    assert not result.errors and len(result.records) == 1


def test_invalid_decision_rejected(api):
    h = {"Content-Type": "application/json", "X-Review-Token": "sekrit"}
    ev = json.dumps({"doc_id": "d", "person": "X", "decision": "maybe"}).encode()
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(api + "/decisions", data=ev, headers=h)
    assert e.value.code == 400


def test_export_excludes_flags_by_default(api):
    h = {"Content-Type": "application/json", "X-Review-Token": "sekrit"}
    ev = json.dumps({"doc_id": "d2", "person": "Someone", "outremer_id": "AUTH:CR1",
                     "decision": "flag", "client_id": "rev-c"}).encode()
    _req(api + "/decisions", data=ev, headers=h)
    _, export = _req(api + "/export")
    assert all(r["decision"] != "flag" for r in export)
    _, export_all = _req(api + "/export?include_flags=1")
    assert any(r["decision"] == "flag" for r in export_all)
