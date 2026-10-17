"""The outremer MCP server (Epic 22, #129/#130): tools over the published data,
and the wire — an end-to-end round trip through the official MCP client against
a running server, mounted at a sub-path the way nginx expects it.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from outremer_mcp import server
from outremer_mcp.corpus import Corpus

AUTHORITY = {
    "schema_version": 2, "generated_at": "2026-10-11T03:15:00+00:00", "record_count": 2,
    "persons": [
        {"authority_id": "AUTH:CR184", "preferred_label": "Godfrey of Bouillon", "type": "person",
         "name": {"name": "Godfrey", "toponym": "Bouillon"},
         "variants": ["Duke Godfrey", "Godefroy de Bouillon", "Godfrey"],
         "variant_provenance": {"Godfrey": [{"system": "test", "locator": "x", "bare": "attested"}]},
         "identifiers": {"wikidata_qid": "Q182351",
                         "wikidata_qid_provenance": {"status": "asserted", "system": "test"}}},
        {"authority_id": "AUTH:CR187", "preferred_label": "Urban II", "type": "person",
         "name": {"name": "Urban", "regnal": "II"}, "variants": ["Pope Urban II"], "identifiers": {}},
    ],
}
DOC = {
    "doc_id": "munro-popescrusades-1916", "source_file": "data/raw/x.pdf",
    "metadata": {"title": "The Popes and the Crusades", "author": "Munro", "year": 1916, "language": "en"},
    "persons": [
        {"name": "Pope Urban II", "raw_mention": "Pope Urban IL", "role": "pope", "group": False,
         "context": "The First Crusade was the work of Pope Urban IL."},
        {"name": "Duke Godfrey", "raw_mention": "Duke Godfrey", "group": False,
         "context": "Duke Godfrey took the cross."},
        {"name": "the clergy", "raw_mention": "the clergy", "group": True, "context": "the clergy"},
    ],
    "links": [
        {"person": "Pope Urban II", "status": "high", "confidence": 1.0,
         "candidates": [{"outremer_id": "AUTH:CR187", "outremer_name": "Urban II", "score": 1.0, "relevance": 0.4}],
         "top_candidate": {"outremer_id": "AUTH:CR187", "outremer_name": "Urban II", "score": 1.0, "relevance": 0.4},
         "rerank": {"veto": False}},
        {"person": "Duke Godfrey", "status": "no_match", "confidence": 0.0,
         "candidates": [{"outremer_id": "AUTH:CR184", "outremer_name": "Godfrey of Bouillon", "score": 1.0, "relevance": 0.18}],
         "top_candidate": None, "rerank": {"veto": True}},
    ],
    "run_at": "2026-10-15T01:36:00+00:00",
    "linking_engine": {"reranker": {"checked": 2, "vetoed": 1, "errors": 0}},
}
STATUS = {"run": {"run_at": "2026-10-15T01:36:00+00:00", "extraction_model": "qwen3.8-27b",
                  "models": {"text": {"model": "qwen3.8-27b", "source": "EXTRACTION_MODEL"}}},
          "gate": {"status": "pass", "errors": []},
          "evaluation": {"segments": {"linking": {"lift": 0.169}}}}


@pytest.fixture
def site_data(tmp_path: Path) -> Path:
    (tmp_path / "authority.json").write_text(json.dumps(AUTHORITY))
    (tmp_path / "munro-popescrusades-1916.json").write_text(json.dumps(DOC))
    (tmp_path / "status.json").write_text(json.dumps(STATUS))
    (tmp_path / "wikidata_matches.json").write_text("{}")
    return tmp_path


@pytest.fixture
def corpus(site_data: Path) -> Corpus:
    c = Corpus(site_data, explorer_url="https://example.test/outremer/").load()
    server.set_corpus(c)
    return c


# ── tools ────────────────────────────────────────────────────────────────────

def test_corpus_stats_reports_records_documents_gate_and_bands(corpus):
    st = server.corpus_stats()
    assert st["authority"]["records"] == 2 and st["authority"]["wikidata_qid"] == {"asserted": 1, "none": 1}
    assert st["documents"][0]["doc_id"] == "munro-popescrusades-1916" and st["documents"][0]["mentions"] == 3
    assert st["links_by_status"] == {"high": 1}, "a vetoed link has no top candidate and no band"
    assert st["last_run"]["gate"] == "pass" and st["last_run"]["models"]["text"]["source"] == "EXTRACTION_MODEL"


def test_search_persons_goes_through_the_linker_and_counts_mentions(corpus):
    hits = server.search_persons("Godefroy de Bouillon", 5)
    assert hits[0]["authority_id"] == "AUTH:CR184" and hits[0]["score"] == 1.0
    assert hits[0]["wikidata_qid"] == "Q182351" and hits[0]["qid_status"] == "asserted"
    assert hits[0]["mentions"] == 0, "the vetoed link is no published mention of this record"
    assert server.search_persons("Pope Urban II")[0]["mentions"] == 1
    assert server.search_persons("") == []
    assert all(h["data_url"].endswith("data/authority.json") for h in hits)


def test_get_person_returns_the_record_with_its_published_mentions(corpus):
    rec = server.get_person("AUTH:CR187")
    assert rec["preferred_label"] == "Urban II" and rec["variants"] == ["Pope Urban II"]
    assert rec["mentions"]["total"] == 1 and rec["mentions"]["by_document"] == {"munro-popescrusades-1916": 1}
    ex = rec["mentions"]["examples"][0]
    assert ex["mention"] == "Pope Urban II" and ex["document"]["author"] == "Munro"
    assert ex["link"]["status"] == "high" and ex["link"]["relevance"] == 0.4
    assert ex["data_url"] == "https://example.test/outremer/data/munro-popescrusades-1916.json"


def test_unknown_id_is_not_found_not_an_outage(corpus):
    """ch-h-bot #497: a prose error alone reads as a provider outage (502)."""
    assert server.get_person("AUTH:CR9999") == {"error": "Person 'AUTH:CR9999' not found.", "not_found": True}
    assert json.loads(server.resource_person("nope"))["not_found"] is True


def test_search_mentions_matches_extracted_and_raw_forms_and_shows_the_veto(corpus):
    hits = server.search_mentions("urban")
    assert [h["mention"] for h in hits] == ["Pope Urban II"]
    assert hits[0]["context"].startswith("The First Crusade") and hits[0]["link"]["authority_id"] == "AUTH:CR187"
    raw = server.search_mentions("Urban IL")
    assert raw and raw[0]["raw_mention"] == "Pope Urban IL"
    godfrey = server.search_mentions("Godfrey")[0]
    assert godfrey["link"]["authority_id"] is None and godfrey["link"]["vetoed"] is True
    assert server.search_mentions("clergy")[0]["group"] is True
    assert server.search_mentions("urban", doc_id="other-doc") == []


def test_the_server_rereads_after_the_nightly_republished(site_data, corpus):
    assert server.corpus_stats()["authority"]["records"] == 2
    more = dict(AUTHORITY, persons=AUTHORITY["persons"] + [
        {"authority_id": "AUTH:CR1", "preferred_label": "Conrad III", "type": "person",
         "name": {"name": "Conrad"}, "variants": [], "identifiers": {}}])
    time.sleep(0.01)
    (site_data / "authority.json").write_text(json.dumps(more))
    (site_data / "status.json").write_text(json.dumps(STATUS) + "\n")
    assert server.corpus_stats()["authority"]["records"] == 3


def test_a_document_newer_than_the_last_gated_run_is_withheld(site_data):
    """2026-10-17: the pipeline rewrote the documents heuristically, the gate
    refused, and status.json still named the last passing run. Such a document
    was never published and must not be served."""
    refused = dict(DOC, doc_id="hamblin-x", run_at="2026-10-17T02:51:26+00:00",
                   extraction_engine={"provider": "heuristic"})
    (site_data / "hamblin-x.json").write_text(json.dumps(refused))
    c = Corpus(site_data).load()
    server.set_corpus(c)
    assert list(c.documents) == ["munro-popescrusades-1916"] and c.withheld == ["hamblin-x"]
    assert server.corpus_stats()["withheld_documents"] == ["hamblin-x"]
    assert all(h["document"]["doc_id"] != "hamblin-x" for h in server.search_mentions("Urban"))


def test_the_tei_unit_reads_the_published_mirror_not_the_work_tree():
    unit = (Path(__file__).resolve().parents[1] / "deploy" / "tei" / "outremer-mcp.user.service").read_text()
    assert "OUTREMER_MCP_SITE_DATA=/var/lib/outremer/state/site/data" in unit
    assert "work/site/data\n" not in unit and "SITE_DATA=%h/outremer/work" not in unit


def test_http_path_is_normalised_to_the_public_form():
    assert server.normalise_path("/mcp/outremer/mcp/") == "/mcp/outremer/mcp"
    assert server.normalise_path("mcp") == "/mcp" and server.normalise_path("") == "/mcp"


# ── the wire ─────────────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def running_server(site_data: Path):
    port = _free_port()
    thread = threading.Thread(
        target=server.main,
        args=(["--site-data", str(site_data), "--host", "127.0.0.1", "--port", str(port),
               "--http-path", "/mcp/outremer/mcp", "--explorer-url", "https://example.test/outremer/"],),
        daemon=True,
    )
    thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as resp:
                if resp.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        pytest.fail("server did not come up")
    return port


def test_health_route_names_the_run_and_its_gate(running_server):
    with urllib.request.urlopen(f"http://127.0.0.1:{running_server}/health", timeout=5) as resp:
        body = json.loads(resp.read())
    assert body == {"status": "ok", "records": 2, "documents": 1, "withheld": 0,
                    "run_at": "2026-10-15T01:36:00+00:00", "gate": "pass"}


def test_official_client_round_trip_at_the_public_path(running_server):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def go():
        url = f"http://127.0.0.1:{running_server}/mcp/outremer/mcp"
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                init = await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                hit = await session.call_tool("search_persons", {"query": "Godefroy de Bouillon", "limit": 1})
                missing = await session.call_tool("get_person", {"authority_id": "AUTH:CR9999"})
                return init, tools, hit, missing

    init, tools, hit, missing = asyncio.run(go())
    assert init.server_info.name == "outremer" and "prosopography" in (init.instructions or "")
    assert tools == {"corpus_stats", "search_persons", "get_person", "search_mentions"}
    assert not hit.is_error
    first = json.loads(hit.content[0].text)
    assert (first if isinstance(first, dict) else first[0])["authority_id"] == "AUTH:CR184"
    body = json.loads(missing.content[0].text)
    assert body["not_found"] is True and not missing.is_error
