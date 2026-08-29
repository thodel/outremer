# Shared research capability adapters

Outremer integrates University of Bern services through provider-neutral
contracts in `scripts/capabilities/`. It does not import the
`agentic_historian` Discord bot, orchestration, deployment state, or
repository-relative application modules. Service differences are contained in
anti-corruption adapters; Outremer evidence, authority candidates, evaluation,
and review decisions remain canonical.

## Registry contract

Every adapter publishes:

- stable capability, provider, contract and contract-version identifiers;
- required/optional and enabled/disabled policy;
- typed tool descriptors with input/output schemas and mutation markers;
- discovery output with availability, sanitized endpoint, provider version and
  discovered tools;
- a single `invoke(tool_id, arguments)` boundary.

`CapabilityRegistry.discover()` makes partial failure visible. A missing optional
provider reports `unavailable` or `disabled` without changing canonical data. A
missing required provider makes the report fail and `require_ready()` blocks the
job. Invocation is blocked unless the provider was discovered as available.

Invocation provenance is append-only JSONL. It records run/invocation/tool and
contract identifiers, provider version, timing, status, error type, and input /
output artifact references with SHA-256 digests. It never records arguments,
responses, source text, or credentials; secret-like keys are rejected.
The registry fails closed on invocation when no audit log is configured.

## Adapters

- **GPUStack:** OpenAI-compatible model discovery, role-routed text/vision,
  embeddings and reranking. It accepts `GPUSTACK_MODEL_*` roles with current
  direct-name variables as compatibility fallbacks until #88 merges.
- **ATR:** health/models, segmentation and attributed recognition/OCR. This is a
  thin shim around the current Outremer `AtrClient`; #87 must replace that import
  with the selected shared package once #90 decides its ownership/versioning.
- **MCP knowledge federation:** streamable-HTTP initialization, tool discovery
  and tool calls. Person results become *unreviewed external candidates* with
  source-local identity preserved; they are never merged directly into an
  Outremer authority record.
- **QLever:** read-only SPARQL. Update operations are rejected even if hidden
  behind `PREFIX`/`BASE` declarations.
- **Voyant:** explicit, mutating corpus hand-off of approved non-empty text.
- **Remote agent tools:** provider-neutral `/tools` discovery and `/invoke` for
  source description, entity, corpus-analysis or reporting contracts that pass
  scholarly-fit review. The adapter does not assume Agent A–E module paths.

## Feature flags

GPUStack is required. Other providers are off unless enabled:

```env
OUTREMER_CAPABILITY_ATR=true
OUTREMER_CAPABILITY_ATR_REQUIRED=false
OUTREMER_CAPABILITY_MCP=false
OUTREMER_CAPABILITY_QLEVER=false
OUTREMER_CAPABILITY_VOYANT=false
OUTREMER_CAPABILITY_AGENT_TOOLS=false
```

Endpoints and credentials retain their service-specific variables:
`GPUSTACK_BASE_URL`, `GPUSTACK_API_KEY`, `ATR_GATEWAY_URL`, `ATR_API_KEY`,
`MCP_BASE_URL`, `MCP_API_KEY`, `QLEVER_ENDPOINT`, `VOYANT_API_URL`, and
`OUTREMER_TOOL_PROVIDER_URL`. Reports contain endpoint URLs but never keys.

## Startup discovery

```bash
python scripts/discover_capabilities.py \
  --output data/staging/capability-availability.json \
  --invocation-log data/staging/capability-invocations.jsonl \
  --require-ready
```

Services should run discovery before accepting a job. The production preflight
in #112 can consume this report after both PRs merge.

## Live staging smoke test

The safe smoke command performs discovery only: GPUStack model listing, ATR
health/model listing, MCP initialization/tool listing, QLever `ASK`, and a
Voyant landing-page request. It does not publish, update the graph, hand off a
corpus, or invoke a remote agent tool.

```bash
python scripts/capability_smoke.py \
  --require gpustack,atr,mcp,qlever,voyant \
  --output /var/lib/outremer/staging/capability-smoke.json
```

`tests/test_capability_adapters.py` contains an opt-in equivalent marked
`live_backend`; set `OUTREMER_LIVE_CAPABILITY_SMOKE=1` only on the protected
university runner. Offline CI mocks every transport boundary.

## Open dependency boundary

This implementation cannot complete #113 by itself:

1. #90 must select and document package/service ownership.
2. #87 must publish the shared ATR client and remove the private-client shim.
3. The protected university staging run must exercise GPUStack, ATR, one MCP
   source, QLever and Voyant and retain its availability report.

Until those conditions hold, #113 stays open even if this adapter PR merges.
