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


# ── v2: the round trip (M13.3, #179) ────────────────────────────────────────

H = {"Content-Type": "application/json", "X-Review-Token": "sekrit"}


def _post(api, ev, method=None):
    return _req(api + "/decisions", data=json.dumps(ev).encode(), headers=H, method=method)


def test_health_says_whether_writes_need_a_token(api):
    _, body = _req(api + "/health")
    assert body["writes"] == "token"


def test_unresolved_is_accepted_and_supersedes_round_trips(api):
    ev = {"doc_id": "d1", "person": "Peter", "outremer_id": "AUTH:CR53",
          "decision": "unresolved", "client_id": "m19", "supersedes": True,
          "comment": "bare given name"}
    code, _ = _post(api, ev)
    assert code == 201
    _, export = _req(api + "/export")
    assert export[0]["decision"] == "unresolved" and export[0]["supersedes"] is True
    # a plain decision does not carry the key at all (file format)
    _post(api, {"doc_id": "d1", "person": "Hugh", "outremer_id": "AUTH:CR1",
                "decision": "accept", "client_id": "rev-a"})
    _, export = _req(api + "/export")
    assert "supersedes" not in export[1]


def test_delete_is_a_withdrawal_event_not_a_deletion(api):
    _post(api, {"doc_id": "d1", "person": "Hugh", "outremer_id": "AUTH:CR1",
                "decision": "accept", "client_id": "rev-a", "scholar_name": "A."})
    code, _ = _post(api, {"doc_id": "d1", "person": "Hugh", "outremer_id": "AUTH:CR1",
                          "client_id": "rev-a", "scholar_name": "A."}, method="DELETE")
    assert code == 201
    _, health = _req(api + "/health")
    assert health["events"] == 2                      # nothing removed
    _, current = _req(api + "/decisions?doc_id=d1")
    assert [c["decision"] for c in current] == ["unresolved"]
    assert current[0]["comment"] == "withdrawn in the Explorer"
    assert "supersedes" not in current[0]             # other reviewers unaffected


def test_delete_requires_the_token(api):
    ev = json.dumps({"doc_id": "d", "person": "X", "outremer_id": "AUTH:1",
                     "client_id": "rev-a"}).encode()
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(api + "/decisions", data=ev, headers={"Content-Type": "application/json"},
             method="DELETE")
    assert e.value.code == 401


def test_events_since_hands_over_only_what_is_new(api):
    _post(api, {"doc_id": "d1", "person": "A", "outremer_id": "AUTH:1",
                "decision": "accept", "client_id": "r"})
    _, first = _req(api + "/events")
    assert len(first) == 1
    _post(api, {"doc_id": "d1", "person": "B", "outremer_id": "AUTH:2",
                "decision": "reject", "client_id": "r"})
    _post(api, {"doc_id": "d1", "person": "C", "outremer_id": "AUTH:3",
                "decision": "flag", "client_id": "r"})
    _, later = _req(api + "/events?since=" + first[0]["submitted_at"])
    assert [e["person"] for e in later] == ["B"]      # after the stamp, flags excluded
    _, everything = _req(api + "/events?include_flags=1")
    assert [e["person"] for e in everything] == ["A", "B", "C"]


def test_a_v1_database_gains_the_supersedes_column(tmp_path):
    import sqlite3
    db = tmp_path / "v1.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE decision_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, person TEXT NOT NULL,
          outremer_id TEXT NOT NULL DEFAULT '', decision TEXT NOT NULL,
          client_id TEXT NOT NULL DEFAULT 'anonymous', scholar_name TEXT, comment TEXT,
          submitted_at TEXT NOT NULL);
        INSERT INTO decision_events (doc_id, person, outremer_id, decision, submitted_at)
          VALUES ('d', 'Old', 'AUTH:9', 'accept', '2026-08-29T00:00:00+00:00');
    """)
    conn.commit()
    conn.close()
    store = ReviewStore(str(db))
    assert store.events() == [{
        "doc_id": "d", "person": "Old", "outremer_id": "AUTH:9", "decision": "accept",
        "client_id": "anonymous", "scholar_name": None, "comment": None,
        "submitted_at": "2026-08-29T00:00:00+00:00"}]
