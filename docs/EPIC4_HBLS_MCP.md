# Epic 4 — HBLS Knowledge Graph MCP

**Status: DONE** ✅ (M4.1–M4.4 complete as of 2026-07-10)

The HBLS MCP server is live at `https://tei.dh.unibe.ch:8003` (or `http://localhost:8003` on tei).

---

## What was built

A FastAPI + FastMCP server backed by SQLite, containerised as `hbls-mcp`.

**Container:** `hbls-mcp:latest` — running on tei (Docker, port 8003)

**Corpus:** HBLS (Historisches Biographisches Lexikon der Schweiz), 8 Bände (1921–1934):
- 18,244 articles
- 19,707 member records
- 37 MB of full-text content
- FTS5 index for fast full-text search

**Database:** `/home/dh/hbls_mcp/hbls.db` (SQLite, read-only, query_only=ON)

---

## API Reference

### REST JSON (FastAPI)

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `GET /mcp` | Full manifest + stats |
| `GET /mcp/stats` | Corpus statistics |
| `GET /mcp/search?q=<query>&limit=N` | Full-text search |
| `GET /mcp/volume/<N>?limit=N&offset=N` | List articles in volume |
| `GET /mcp/article/<headword>/<volume>` | Fetch article by headword+volume |
| `GET /mcp/family/<headword>/<volume>` | Family members |
| `GET /mcp/persons/search?q=<query>&limit=N` | Search all persons |
| `GET /mcp/persons/<pid>` | Get person by ID |
| `GET /mcp/category/<cat>?volume=N` | Articles by category (fam/bio/geo/tem) |
| `GET /mcp/category/stats?volume=N` | Category counts |
| `GET /mcp/page/<volume>/<page>` | Article at volume+page |
| `GET /mcp/hbls/landing` | Human-readable landing page |

### MCP Tools (FastMCP SSE)

Connect via SSE at `http://tei.dh.unibe.ch:8003/sse`.

| Tool | Description |
|---|---|
| `corpus_stats` | High-level counts |
| `search` | Full-text search |
| `get_article` | Article by headword+volume |
| `get_article_by_page` | Article at volume+page |
| `list_volume` | Articles in a volume |
| `get_family_members` | Family members |
| `search_persons` | Search all persons |
| `search_bio` | Search bio articles only |
| `get_pdf_url` | PDF page URL |
| `get_articles_by_category` | By category |
| `get_category_stats` | Category counts |

---

## Deployment

### On tei (current)

The container is managed by Docker Compose:

```bash
# View status
docker ps | grep hbls

# Logs
docker logs <container_id>

# Restart
docker-compose -f /path/to/docker-compose.yml restart

# Rebuild after code changes
docker build -t hbls-mcp:latest .
docker stop <old_container> && docker run -d --restart unless-stopped \
  -p 8003:8003 \
  -v /home/dh/hbls_mcp/hbls.db:/home/dh/hbls_mcp/hbls.db:ro \
  --read-only \
  hbls-mcp:latest --db /home/dh/hbls_mcp/hbls.db --host 0.0.0.0 --port 8003
```

### Database location

- **Container path:** `/home/dh/hbls_mcp/hbls.db` (read-only mounted)
- **Host path:** `/home/dh/hbls_mcp/hbls.db`
- **Build script:** `docker exec <cid> cat /app/build_hbls_db.py`

### Port

**Port 8003** — confirmed free and in use by `hbls-mcp:latest`.

---

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M4.1 Clone + understand schema | ✅ Done | Schema: articles, members, fts_articles tables |
| M4.2 FastAPI MCP /health, /search, /persons | ✅ Done | All endpoints implemented |
| M4.3 Fuzzy name matching + year filter | ✅ Done | FTS5 + rapidfuzz available in search |
| M4.4 Dockerise + port docs | ✅ Done | Docker image built, running, documented |

---

## Open Questions (resolved)

- **Docker vs bare FastAPI?** → Docker chosen, running as `hbls-mcp:latest`
- **Port 8003 free?** → Confirmed, container is bound to it
- **EOS persons vs HBLS?** → HBLS MCP serves the HBLS (HLS predecessor). EOS persons data (`/home/dh/eos_persons/`) is separate data for Königsfelden cross-references.

---

## Cross-reference with OUTREMER

The HBLS MCP is primarily a data source for the OUTREMER knowledge graph. The `wikidata_reconcile.py` script and `build_unified_kg.py` do not currently query the HBLS MCP — this is a potential future integration point (Epic 5 or later).