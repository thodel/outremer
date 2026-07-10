# OUTREMER — GPUStack Adaptation Progress

> **Status: In progress** — Epic 1-7 done, Epic 8 in progress

| Date | Commit | Change |
|---|---|---|
| 2026-07-10 | 4675642 | Epic 4 M4.4 + Epic 6 + Epic 7: HBLS MCP docs, repo hygiene, GPUStack .env bugfix, README rewrite |
| 2026-07-10 | f97cd00 | Epic 4: M4.1-M4.3 HBLS MCP Docker + API (container running on port 8003) |
| 2026-07-05 | d2785e9 | Epic 1: M1.1-M1.5 GPUStack migration |
| 2026-07-05 | f2885a7 | Epic 2: M2.1-M2.4 JSON repair, chunk, retry, reports |
| 2026-07-05 | 18fb483 | Epic 3: M3.1 NFC normalisation |

Epic 5 (CI/CD, #14) and Epic 8 (Feedback, #17) not yet started.

Commit history:
| Date | Commit | Change |
|---|---|---|
| 2026-07-10 | (docs) | Epic 4 M4.4: HBLS MCP documentation + landing page |
| 2026-07-05 | d2785e9 | Epic 1: M1.1-M1.5 GPUStack migration |
| 2026-07-05 | f2885a7 | Epic 2: M2.1-M2.4 JSON repair, chunk, retry, reports |
| 2026-07-05 | 18fb483 | Epic 3: M3.1 NFC normalisation |
| 2026-07-05 | f97cd00 | Epic 4: M4.1-M4.3 HBLS MCP Docker + API (container running on port 8003) |

Epic 5 (CI/CD, #14) and Epic 8 (Feedback, #17) — see LOCAL_LLM_ADAPTATION_PLAN.md for full Epic 5-8 scope.

## What was done today (2026-07-10)

### Epic 6 — Repo Hygiene
- **M6.1** Peerage export data moved from `scripts/peerage_pre1500_export/` → `data/peerage_pre1500_export/`
- **M6.2** Canonical `install-triplestore.sh` replaces 6 separate install scripts
- **M6.3** Removed 6 superseded install-graphdb scripts; archived 12 stale docs from 2026-02
- **M6.4** `docs/README.md` living docs index + curated active docs

### Epic 7 — Documentation
- **M7.1** README rewritten GPUStack-first with full architecture + API reference
- **M7.2** Fixed `config.py` to actually load `.env.gpustack` (was missing the dotenv loading code); added `python-dotenv` dep

### Epic 4 — HBLS MCP
- **M4.4** `docs/EPIC4_HBLS_MCP.md` — full deployment + API reference for Docker HBLS MCP (port 8003)
