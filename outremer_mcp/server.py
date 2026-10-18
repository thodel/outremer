"""outremer MCP server (mcp 2.0 MCPServer, streamable HTTP) — Epic 22, #129/#130.

Run from the repo root:

    python -m outremer_mcp.server --site-data site/data --port 8014 \
        --http-path /mcp/outremer/mcp

Behind nginx the server must be mounted at its *public* path: the route only
matches what it was mounted at, so ``--http-path`` and the nginx ``location``
must agree exactly or every request 404s (tei fleet rule; never SSE behind a
sub-path). Port 8014 is the first free one on tei after the fleet's 8000–8013.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from outremer_mcp.corpus import Corpus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Defaults from the environment so that importing never touches sys.argv.
DEFAULT_SITE_DATA = os.environ.get("OUTREMER_MCP_SITE_DATA", "site/data")
DEFAULT_HOST = os.environ.get("OUTREMER_MCP_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("OUTREMER_MCP_PORT", "8014"))
DEFAULT_EXPLORER = os.environ.get("OUTREMER_MCP_EXPLORER_URL", "https://tei.dh.unibe.ch/outremer/")
# Public host names nginx forwards (comma-separated). mcp 2.x guards against
# DNS rebinding and, on a loopback bind, admits only localhost Host headers —
# so behind nginx, which forwards Host: tei.dh.unibe.ch, every request got
# "421 Invalid Host header" (2026-10-18). These names are added to the
# loopback defaults; the guard stays on and any other Host is still refused.
DEFAULT_ALLOWED_HOSTS = os.environ.get("OUTREMER_MCP_ALLOWED_HOSTS", "")

LOOPBACK_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOOPBACK_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def transport_security(public_hosts: str) -> TransportSecuritySettings:
    """The loopback defaults of mcp, plus each public host (bare and with a port)."""
    names = [h.strip() for h in (public_hosts or "").split(",") if h.strip()]
    hosts = LOOPBACK_HOSTS + [v for n in names for v in (n, f"{n}:*")]
    origins = LOOPBACK_ORIGINS + [f"https://{n}" for n in names]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=hosts, allowed_origins=origins)


def normalise_path(path: str | None) -> str:
    """A single leading slash, no trailing slash — the form the ASGI route wants."""
    cleaned = (path or "").strip().strip("/")
    return f"/{cleaned}" if cleaned else "/mcp"


DEFAULT_HTTP_PATH = normalise_path(os.environ.get("OUTREMER_MCP_HTTP_PATH", "/mcp"))

INSTRUCTIONS = (
    "outremer — AI-assisted prosopography of the medieval Levant (crusades and the "
    "Latin East, c. 1095–1291). Two things are served, both read-only and only as "
    "published after the project's provenance gate: an AUTHORITY FILE of persons "
    "(ids AUTH:CR…, name forms with their provenance, Wikidata QIDs with a status: "
    "asserted, hypothesised or none) and the MENTIONS the pipeline extracted from "
    "three scholarly articles (Riley-Smith 1983, Munro 1916, Hamblin 2001), each "
    "with its context sentence and its machine-proposed link to a record.\n\n"
    "Use search_persons for a name (fuzzy, through the project's own linker; a hit "
    "lists score and evidence), get_person for one record with its name forms, "
    "identifiers and where it is mentioned, search_mentions for passages that "
    "name a person (with context and the document), and corpus_stats for what "
    "is there and when it was last run.\n\n"
    "Read the links as what they are: machine proposals with a status band "
    "(high/medium) and, since 2026-10-14, a reranker veto — not scholarly "
    "assertions. A mention is evidence that a text names someone; the record it "
    "links to is a hypothesis unless adjudicated. The contexts are short "
    "extracts; the articles themselves are not served. Every hit carries the "
    "Explorer URL and the URL of the published JSON it came from."
)

mcp = MCPServer(name="outremer", version="1.0.0", instructions=INSTRUCTIONS)

_corpus: Corpus | None = None


def corpus() -> Corpus:
    global _corpus
    if _corpus is None:
        _corpus = Corpus(Path(DEFAULT_SITE_DATA), explorer_url=DEFAULT_EXPLORER).load()
    _corpus.maybe_reload()
    return _corpus


def set_corpus(c: Corpus) -> None:
    global _corpus
    _corpus = c


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def corpus_stats() -> dict:
    """What is served: authority records (and how many carry a Wikidata QID, by
    status), the documents with their mention and link counts, the last nightly
    run with its gate verdict and model roles."""
    return corpus().stats()


@mcp.tool()
def search_persons(query: str, limit: int = 10) -> list[dict]:
    """Find authority records by name — preferred label or any recorded name form,
    fuzzy, through the same linker the pipeline uses. Each hit carries its score,
    the matched form (evidence), the QID with its status, and how many published
    mentions link to it. Lower scores are candidates, not identifications."""
    return corpus().search_persons(query, limit)


@mcp.tool()
def get_person(authority_id: str) -> dict:
    """One authority record by id (e.g. AUTH:CR184): name structure, every name
    form with its provenance, identifiers (Wikidata QID and how it was
    established), and the published mentions linked to it, by document."""
    result = corpus().get_person(authority_id)
    if result is None:
        return {"error": f"Person {authority_id!r} not found.", "not_found": True}
    return result


@mcp.tool()
def search_mentions(query: str, limit: int = 20, doc_id: str = "") -> list[dict]:
    """Passages in which a person is named: the extracted mention, its context
    sentence, the document (author, title, year) and the machine-proposed link
    with its status. `doc_id` restricts to one document (see corpus_stats).
    Matches the mention as extracted and as written (raw_mention)."""
    return corpus().search_mentions(query, limit, doc_id)


# ── Resources ─────────────────────────────────────────────────────────────────

@mcp.resource("outremer://stats")
def resource_stats() -> str:
    return json.dumps(corpus().stats(), indent=2, ensure_ascii=False)


@mcp.resource("outremer://person/{authority_id}")
def resource_person(authority_id: str) -> str:
    result = corpus().get_person(authority_id)
    if result is None:
        return json.dumps({"error": f"Person {authority_id!r} not found.", "not_found": True})
    return json.dumps(result, indent=2, ensure_ascii=False)


# ── Health ────────────────────────────────────────────────────────────────────

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request) -> JSONResponse:
    """For nginx's /mcp/outremer/health and the cron healthcheck (#131): says
    whether the data loaded, from which run, and whether its gate passed."""
    try:
        c = corpus()
        run = (c.status.get("run") or {})
        return JSONResponse({
            "status": "ok", "records": len(c.records), "documents": len(c.documents),
            "withheld": len(c.withheld),
            "run_at": run.get("run_at"), "gate": (c.status.get("gate") or {}).get("status"),
        })
    except Exception as exc:  # the data directory is missing or unreadable
        return JSONResponse({"status": "error", "error": str(exc)[:200]}, status_code=503)


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="outremer MCP server")
    ap.add_argument("--site-data", default=DEFAULT_SITE_DATA,
                    help="published site/data directory (env OUTREMER_MCP_SITE_DATA)")
    ap.add_argument("--host", default=DEFAULT_HOST, help="bind address (env OUTREMER_MCP_HOST)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (env OUTREMER_MCP_PORT)")
    ap.add_argument("--http-path", default=DEFAULT_HTTP_PATH,
                    help="path the MCP endpoint is served at; the PUBLIC path behind "
                         "a reverse proxy (env OUTREMER_MCP_HTTP_PATH)")
    ap.add_argument("--explorer-url", default=DEFAULT_EXPLORER,
                    help="URL hits cite (env OUTREMER_MCP_EXPLORER_URL)")
    ap.add_argument("--allowed-hosts", default=DEFAULT_ALLOWED_HOSTS,
                    help="comma-separated public Host names a reverse proxy forwards "
                         "(env OUTREMER_MCP_ALLOWED_HOSTS); loopback is always allowed")
    args = ap.parse_args(argv)
    args.http_path = normalise_path(args.http_path)
    return args


def main(argv=None) -> None:
    args = parse_args(argv)
    set_corpus(Corpus(Path(args.site_data), explorer_url=args.explorer_url).load())
    c = corpus()
    logger.info("site data: %s — %d records, %d documents, gate %s, run %s",
                args.site_data, len(c.records), len(c.documents),
                (c.status.get("gate") or {}).get("status"), (c.status.get("run") or {}).get("run_at"))
    security = transport_security(args.allowed_hosts)
    logger.info("Starting outremer MCP server on %s:%s%s (hosts: %s)", args.host, args.port,
                args.http_path, ", ".join(security.allowed_hosts))
    mcp.run(transport="streamable-http", host=args.host, port=args.port,
            streamable_http_path=args.http_path, transport_security=security)


if __name__ == "__main__":
    main()
