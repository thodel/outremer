# ADR 0002: How outremer and agentic_historian share code

- **Status:** Accepted — 2026-10-15
- **Decision owner:** Tobias Hodel (maintainer of all three repositories)
- **Tracking:** #90 (this decision), #87 (first application: the ATR gateway client), Epic #68
- **Supersedes:** the "until #88 merges" and "once #90 decides" placeholders in
  [`CAPABILITY_ADAPTERS.md`](../CAPABILITY_ADAPTERS.md)

## Context

Two independently released research repositories call the same service, the
ATR recognition gateway [`thodel/serving-atr-inference`](https://github.com/thodel/serving-atr-inference)
on idhefix (`:8200`, `X-API-Key`, `GET /health`, `GET /models`,
`POST /segment`, `/recognize`, `/ocr`):

- [`thodel/agentic_historian`](https://github.com/thodel/agentic_historian),
  `agentic_historian/agent_a/kraken_client.py` — `KrakenHTTPClient`,
  `KrakenResult`, `KrakenClientError(status_code)`.
- this repository, `scripts/atr_client.py` — `AtrClient`, `AtrResult`,
  `AtrClientError`.

#87 was filed on the premise that the two hold "near-identical code". By the
time of this decision they do not, and the divergence is the evidence this ADR
rests on:

| behaviour | agentic_historian | outremer |
|---|---|---|
| unknown engine (e.g. a vllm model) | `read()` routes it to `/recognize` — learned in its #540 when the gateway gained vLLM models and every one of them was unreachable | `transcribe()` raises `ValueError("kraken and trocr")` — a vllm model has no path |
| result fields | text, confidence, model, version **plus** per-line readings, `engine`, `segmented_by`, `timing_ms` (`None` ≠ `0`, its #595), `truncated`, `second_opinion` | text, confidence, model, engine, version |
| error status | carried as `status_code` (`None` = never answered) so a batch can tell a retryable 502 from a permanent 404 (its #174 in the gateway) | in the message text only |
| timeout default | 300 s from config, with a test that it is never tighter than the gateway's engine budget | 300 s from config, same test |

Neither copy is wrong for its caller today; each has absorbed lessons the other
has not. That is what a copy does: it stops being a copy. This project has
seen it twice before — the Wikidata resolver vendored from
`wikidata_pre1500_mcp` drifts from its source, and the MCP provider pattern of
the tei fleet carries three "identical" files per corpus that have to be
re-synced by hand.

Facts that constrain the mechanism:

1. **All three repositories are public.** A dependency pinned to a GitHub URL
   needs no token, in CI, in Docker or on tei.
2. **Every consumer installs from a file, before any air gap.** outremer's
   nightly runs `pip install -r requirements.lock.txt` (then the pipeline
   under `--airgap`), CI and the Docker build install the same lock,
   agentic_historian installs `requirements.txt`. A URL pin is just another line.
3. **The outremer image is `python:3.12-slim` without `git`.** A `git+https://`
   pin would fail the Docker build; an archive URL does not need git.
4. **The gateway repository already owns the wire contract.**
   `src/atr_serving/contracts.py` (pydantic only, "zero heavy deps") is
   imported by the gateway and every engine service, and its test suite runs
   the real FastAPI app with `TestClient`. A client can be tested against the
   actual routes only there; a consumer can only mock them.
5. **Nothing here is on PyPI, and nothing needs to be.** A publishing step is
   one more place for the shared code and the served code to disagree.
6. **The gateway repository has no tags yet.** A pin must therefore be a
   commit SHA; tags are labels we may add, not what the pin relies on.

## Decision

### 1. Shared code is a pip package owned by the repository that owns the contract

The ATR client becomes the distribution **`atr-client`** (import name
`atr_client`) and lives in **`thodel/serving-atr-inference` under
`clients/python/`**, with its own `pyproject.toml`, next to the API it talks
to. The gateway's CI installs it and runs its offline suite together with a
contract test against the gateway app. A change to a route ships with the
client change in the same pull request, or the gateway's own CI is red.

Both consumers install it; neither keeps a copy. outremer deletes
`scripts/atr_client.py`; agentic_historian keeps `agent_a/kraken_client.py`
only as a re-export shim (`KrakenHTTPClient = AtrClient`, `KrakenResult =
AtrResult`, `KrakenClientError = AtrClientError`, `endpoint_for`,
`OCR_ENGINES`, `kraken_transcribe`), so its call sites and its
`KRAKEN_SERVICE_URL` fallback keep working unchanged.

The same rule applies to the next piece of shared code: it lives with the
repository that owns the contract it implements, as an installable package;
if no repository owns the contract, that is the question to settle first.

### 2. Pinning: an archive URL on a commit SHA, bumped in a pull request

Each consumer pins the package to a 40-character commit SHA of the gateway
repository, in the file it installs from:

```
atr-client @ https://github.com/thodel/serving-atr-inference/archive/<sha>.tar.gz#subdirectory=clients/python
```

- outremer: `requirements.lock.txt` (and `requirements.txt`, so a regenerated
  lock keeps it). agentic_historian: `requirements.txt`.
- A bump is a pull request in the consumer; its CI is where a client change
  shows up. Nothing bumps itself.
- The gateway maintainers own releases: they may tag a client change
  `client-vX.Y.Z` for readability, but the pin is the SHA, so a moved tag can
  never change what a consumer runs.
- A test in each consumer asserts that `atr_client` is imported from
  `site-packages`, not from the repository tree, and that the pin is a
  40-hex SHA archive URL. A vendored copy reappearing fails CI.

### 3. Who owns which operational constant

| constant | owner | where it lives |
|---|---|---|
| `ATR_HTTP_TIMEOUT` default **300 s** (the gateway's engine budget: 120 s manufactured phantom timeouts, agentic_historian 2026-07-16) | gateway | `atr_client` default; consumers may override via env |
| `/ocr` accepts kraken and trocr only, everything else goes to `/recognize` (`endpoint_for`, agentic_historian #540) | gateway | `atr_client.OCR_ENGINES`, `endpoint_for()` |
| error semantics: `status_code` on the exception, `None` when the gateway never answered | gateway | `atr_client.AtrClientError` |
| the env names `ATR_GATEWAY_URL`, `ATR_API_KEY`, `ATR_HTTP_TIMEOUT` | gateway | `AtrClient.from_env()`; consumer configs keep their own copies for their other code |
| retry and backoff policy | consumer | none in the client: whether to retry a 502 is a batch runner's decision (agentic_historian retries, outremer's nightly fails loudly) |
| `KRAKEN_SERVICE_URL` legacy fallback | agentic_historian | its `config.py` and shim only |
| `ENSEMBLE_NO_MERGE_CER` 0.35 (BAT_664), `VLM_FREQUENCY_PENALTY` 0.2, `EXTRACTION_MAX_TOKENS`, the role → model mapping | each consumer | its own `config.py`. These are recognition and extraction **policy**, tuned per corpus; a number copied from the other repository is cited with the issue that measured it, never imported |

### 4. What is not shared

Evidence-first records, the authority model, evaluation and review semantics
stay outremer's (ADR 0001); the ensemble, the Discord bot and the batch runner
stay agentic_historian's. Shared means "the same contract, implemented once",
not "the same project".

## Alternatives considered

- **Vendored module with a sync check.** Rejected on the evidence above: the
  two clients are already a fork of each other, the Wikidata resolver drifts
  the same way, and a sync check that is red is a copy nobody wants to touch.
  "A copy left behind becomes a fork."
- **Git submodule.** Rejected: the tei nightly's `git pull --rebase
  --autostash`, the dh-bot's `-dev` clones, the Docker build context and the
  release venv would all need submodule handling, and the first one that is
  forgotten runs stale code silently.
- **Package inside agentic_historian.** Rejected: it is a consumer, not the
  contract owner, and installing it pulls `py-cord`, `webdav4` and the rest of
  a Discord bot into a prosopography pipeline.
- **A fourth repository `thodel/atr-client`.** Rejected: 200 lines in their own
  repository, tested against the gateway only by mocking it, when the gateway
  repository can run the real app in its tests.
- **PyPI or an internal index.** Rejected: nothing private is involved and a
  publishing step is one more thing to forget between "merged" and "installed".
- **`git+https://` pins.** Rejected for the mechanism, not the idea: the
  outremer image has no `git`. Archive URLs are the same pin without the tool.

## Consequences

- The gateway's CI gains the client's tests; a route change that breaks a
  consumer is caught where the route is changed.
- A consumer sees a client change only when it bumps the SHA. That is the
  point: production on tei runs what its lock names.
- The air gap is unaffected: the install precedes the guard, and the client
  only ever talks to `ATR_GATEWAY_URL`, which the guard permits.
- Where the shared code lives and how to change it is now one sentence for a
  new contributor: *edit `clients/python/` in serving-atr-inference, let its
  CI pass, then bump the SHA in the consumer that needs the change.*
