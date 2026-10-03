"""Offline QID resolution against the pre-1500 snapshot (M17.1, #83).

The acceptance of #83 is "reconciliation runs with no outbound network call and
its snapshot version appears in provenance", so that is what these assert —
including a test that breaks `urlopen` and still expects an answer, because an
accidental live call is exactly the regression this milestone exists to prevent.
"""

import json
import sqlite3

import pytest
import wikidata_reconcile
import wikidata_snapshot

SCHEMA = """
CREATE TABLE persons (qid TEXT PRIMARY KEY, label TEXT, description TEXT,
                      birth_year INTEGER, death_year INTEGER, hydrated_at TEXT);
CREATE TABLE names (qid TEXT, name TEXT, lang TEXT, kind TEXT);
CREATE VIRTUAL TABLE names_fts USING fts5(name, qid UNINDEXED,
                                          tokenize='unicode61 remove_diacritics 2');
CREATE TABLE snapshot (key TEXT PRIMARY KEY, value TEXT);
"""


@pytest.fixture
def snapshot_path(tmp_path):
    path = tmp_path / "wd-pre1500.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO persons VALUES(?,?,?,?,?,'2026-10-02')", [
        ("Q101866", "Gregory VIII", "pope", 1100, 1187),
        ("Q37594", "Saladin", "sultan of Egypt and Syria", 1137, 1193),
        ("Q102", "Gregory", "abbot", 1210, 1288),
    ])
    names = [("Q101866", "Gregory VIII", "en", "label"),
             ("Q101866", "Albertus de Morra", "la", "alias"),
             ("Q101866", "Gregory", "en", "alias"),
             ("Q37594", "Saladin", "en", "label"),
             ("Q37594", "Salah ad-Din", "en", "alias"),
             # A second bearer of the bare given name, which is what makes
             # "Gregory" a tie rather than an answer.
             ("Q102", "Gregory", "en", "label")]
    con.executemany("INSERT INTO names VALUES(?,?,?,?)", names)
    con.executemany("INSERT INTO names_fts(name, qid) VALUES(?,?)",
                    [(n, q) for q, n, _, _ in names])
    con.execute("INSERT INTO snapshot VALUES('built_at','2026-10-02T21:00:00+00:00')")
    con.commit()
    con.close()
    return path


@pytest.fixture
def offline(monkeypatch, snapshot_path):
    """The reconciler, configured for the snapshot and cut off from the network."""
    import config

    monkeypatch.setattr(config, "WIKIDATA_SNAPSHOT", str(snapshot_path), raising=False)
    monkeypatch.setattr(wikidata_reconcile, "_SNAPSHOT", None)

    def no_network(*args, **kwargs):
        raise AssertionError("reconciliation made an outbound request")

    monkeypatch.setattr(wikidata_reconcile, "urlopen", no_network)
    return wikidata_reconcile


# ── #83's acceptance ──────────────────────────────────────────────────────────
def test_resolution_makes_no_outbound_request(offline):
    """`urlopen` raises if touched; an answer here means nothing left the box."""
    answer = offline.resolve("Albertus de Morra")

    assert answer["status"] == "match"
    assert answer["candidates"][0]["qid"] == "Q101866"


def test_every_answer_carries_the_snapshot_version(offline):
    answer = offline.resolve("Saladin")

    assert answer["snapshot"] == "2026-10-02T21:00:00+00:00"
    assert answer["source"] == "wikidata_pre1500_snapshot"


def test_a_miss_is_stated_not_an_empty_list(offline):
    """Before #83 an empty list meant both "asked, nothing" and "never asked"."""
    answer = offline.resolve("Hattin of Nowhere")

    assert answer["status"] == "no_candidates"
    assert answer["candidates"] == []
    assert answer["snapshot"] == "2026-10-02T21:00:00+00:00"


# ── the candidates keep the shape the explorer reads ──────────────────────────
def test_a_candidate_has_the_fields_the_ui_expects(offline):
    candidate = offline.resolve("Salah ad-Din")["candidates"][0]

    assert candidate["qid"] == "Q37594"
    assert candidate["url"] == "https://www.wikidata.org/wiki/Q37594"
    assert set(candidate) >= {"qid", "label", "description", "url", "score",
                              "birth_year", "death_year"}
    assert candidate["death_year"] == 1193 and candidate["score"] == 1.0


def test_the_matched_variant_is_named(offline):
    """Which spelling scored is the difference between a result and a claim."""
    assert offline.resolve("Albertus de Morra")["candidates"][0]["matched"] == \
        "Albertus de Morra"


# ── the fold and the scorer, as vendored ──────────────────────────────────────
def test_the_vendored_scorer_matches_the_upstream_cases():
    """These are the cases wikidata_pre1500_mcp was measured on; the two files
    must not drift apart, or the fleet and the nightly name different people."""
    assert wikidata_snapshot.score("Albertus de Morra", "Albertus de Morra") == 1.0
    assert wikidata_snapshot.score("Jean de Vaunoise", "Albertus de Morra") == 0.0
    assert wikidata_snapshot.score("Henry V", "Henry V") == 1.0
    assert wikidata_snapshot.score("Gregorius VIII", "Gregorius VII") < 1.0
    assert wikidata_snapshot.normalise("Iohannes") == wikidata_snapshot.normalise("Johannes")
    assert wikidata_snapshot.normalise("Henry V") == "henry v"


def test_extraction_noise_resolves_to_nothing():
    """The reconciler is fed whatever the extractor could not link, and a lot of
    that is not a name: of 1,881 cached entries here, "Popes", "Vol", "April",
    "This" and "First" are typical. The live path answered Voltaire for "Vol".
    A single word under five letters must carry no match at all."""
    assert wikidata_snapshot.score("This", "Tuệ Tĩnh") == 0.0
    assert wikidata_snapshot.score("Vol", "Voltaire") == 0.0
    assert wikidata_snapshot.score("Morra", "Albertus de Morra") == 0.6


# ── a tie is not an identification ────────────────────────────────────────────
def test_a_name_several_people_share_is_ambiguous(offline):
    """The defect this found: the published matches said "match" for 310 of 652
    names that fitted more than one person — "Alexander" is the exact label of 21
    in the real snapshot — and the explorer's TEI and JSON-LD exports turned
    candidate[0] into <idno type="wikidata"> and owl:sameAs with nobody looking."""
    answer = offline.resolve("Gregory")

    assert answer["status"] == "ambiguous"
    assert answer["fits"] == 2


def test_an_unambiguous_name_stays_a_match(offline):
    answer = offline.resolve("Albertus de Morra")

    assert answer["status"] == "match" and answer["fits"] == 1


def test_the_run_records_how_many_people_a_name_fits(tmp_path, offline):
    """`fits` has to reach the published file, because that is where the exports
    read it: a reviewer cannot weigh a candidate without knowing the tie."""
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "doc.json").write_text(json.dumps({
        "doc_id": "doc", "links": [{"person": "Gregory", "status": "no_match"}]}),
        encoding="utf-8")

    offline.run(site, limit=3)

    written = json.loads((site / "data" / "wikidata_matches.json").read_text())
    entry = written["doc"][wikidata_reconcile.normalise("Gregory")]
    assert entry["status"] == "ambiguous" and entry["fits"] == 2


def test_the_live_path_cannot_count_a_tie(monkeypatch):
    """It only ever saw the rows the endpoint chose to return, so `fits` is null
    rather than 1 — a number there would claim a uniqueness nobody checked."""
    import config

    monkeypatch.setattr(config, "WIKIDATA_SNAPSHOT", "", raising=False)
    monkeypatch.setattr(wikidata_reconcile, "_SNAPSHOT", None)
    monkeypatch.setattr(wikidata_reconcile, "reconcile_person",
                        lambda name, limit=3: [{"qid": "Q1", "score": 1.0}])

    assert wikidata_reconcile.resolve("anybody")["fits"] is None


# ── degrading, not crashing ───────────────────────────────────────────────────
def test_an_unusable_snapshot_path_warns_and_uses_the_live_path(monkeypatch, caplog):
    import config

    monkeypatch.setattr(config, "WIKIDATA_SNAPSHOT", "/nowhere/missing.db", raising=False)
    monkeypatch.setattr(wikidata_reconcile, "_SNAPSHOT", None)
    monkeypatch.setattr(wikidata_reconcile, "reconcile_person", lambda name, limit=3: [])

    answer = wikidata_reconcile.resolve("anybody")

    assert answer["source"] == wikidata_reconcile.LIVE
    assert answer["status"] == "no_candidates" and answer["snapshot"] is None
    assert "unusable" in caplog.text


def test_without_a_snapshot_the_live_path_still_answers(monkeypatch):
    import config

    monkeypatch.setattr(config, "WIKIDATA_SNAPSHOT", "", raising=False)
    monkeypatch.setattr(wikidata_reconcile, "_SNAPSHOT", None)
    monkeypatch.setattr(wikidata_reconcile, "reconcile_person",
                        lambda name, limit=3: [{"qid": "Q1", "score": 0.5}])

    answer = wikidata_reconcile.resolve("anybody")

    assert answer["source"] == wikidata_reconcile.LIVE
    assert answer["status"] == "match" and answer["snapshot"] is None


# ── what the run writes ───────────────────────────────────────────────────────
def test_the_run_records_which_backend_resolved(tmp_path, offline, monkeypatch):
    """The published file has to say what produced it, not only what it found."""
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "doc.json").write_text(json.dumps({
        "doc_id": "doc", "links": [{"person": "Saladin", "status": "no_match"}]}),
        encoding="utf-8")

    offline.run(site, limit=3)

    written = json.loads((site / "data" / "wikidata_matches.json").read_text())
    assert written["status"]["source"] == "wikidata_pre1500_snapshot"
    assert written["status"]["snapshot"] == "2026-10-02T21:00:00+00:00"
    entry = written["doc"][wikidata_reconcile.normalise("Saladin")]
    assert entry["status"] == "match" and entry["candidates"][0]["qid"] == "Q37594"


# ── what the explorer may publish ─────────────────────────────────────────────
def test_no_export_asserts_an_identity_nobody_accepted():
    """app.js bootstraps the DOM at load, so this pins the gate the way this repo
    pins UI (see test_unified_evidence_ui.py): by what the source says.

    The defect: both exports took `candidates[0]` — the TEI as
    `<idno type="wikidata">`, the JSON-LD as `owl:sameAs` for anything scoring
    0.4, which includes a prefix match. For a name like "Alexander", exact label
    of 21 people in the snapshot, that published an arbitrary one of them as the
    person's identity, with no reviewer involved. Only an accepted candidate may
    carry an identity claim; the rest are published as candidates.
    """
    from pathlib import Path

    app = (Path(__file__).resolve().parents[1] / "site" / "app.js").read_text(
        encoding="utf-8")

    assert "function acceptedWikidataQid(docId, personName, decisions)" in app
    for claim in ('<idno type="wikidata">', 'entity["owl:sameAs"]'):
        assert claim in app, "the export itself is gone, not only its gate"
    assert 'wikidataCandidatesFor(l.person)[0]' not in app
    assert "wdCands[0].qid" not in app
    assert 'entity["outremer:wikidataCandidate"]' in app, \
        "an unaccepted candidate is still worth publishing, as a candidate"
    assert 'wdEntry.status === "ambiguous"' in app, \
        "a reviewer has to see that the name fits a crowd"
