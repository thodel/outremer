# docs/ — Living Documentation

This directory contains active documentation. Stale/historical documents are in `docs/archive/`.

## Living Docs

| File | Description |
|---|---|
| `LOCAL_LLM_ADAPTATION_PLAN.md` | GPUStack migration plan — Epic 1–8 roadmap, current as of 2026-07 |
| `INTEGRATED_DATA_MODEL.md` | Data model for OUTREMER persons (HBLS + Wikidata + Königsfelden) |
| `EPIC4_HBLS_MCP.md` | HBLS MCP server: deployment, API reference, Docker |
| `PROGRESS.md` | Project-wide progress tracker (root of repo) |

## Archived (historical, may be outdated)

| File | Description |
|---|---|
| `archive/` | Old proposals, morning reports, superseded roadmaps |

## How to Keep Docs Fresh

- Every epic/milestone completion: update `PROGRESS.md`
- New architecture decisions: add new doc, don't overwrite old ones
- Stale docs with dates > 3 months: move to `archive/` after confirming obsolete