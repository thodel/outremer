# Outremer deployment on `tei.dh.unibe.ch`

This directory packages the current Outremer system as two separate concerns:

- `outremer-web.service` serves the generated static research interface on a
  loopback port; nginx publishes it below a configurable URL prefix.
- `outremer-worker.service` is a bounded, one-shot pipeline job. Its timer is
  optional; manual and deployment-runner invocation use the same unit.

Server-side multi-user review/API state is intentionally not invented here; it
belongs to #114. The nginx template reserves `<base>/api/` for that service.

All commands below are an operator runbook, not an automated authorization to
change production. Replace example version `v0.1.0` and paths only after the
deployment ADR (#110) and infrastructure prerequisites are approved.

## Filesystem contract

```text
/opt/outremer/
  releases/<version>/       immutable checkout + .venv
  current -> releases/...   atomic release pointer
/var/lib/outremer/
  source/                   governed source inputs
  state/                    evidence, decisions, run state, generated site
  cache/                    disposable/rebuildable cache (or /var/cache)
/var/backups/outremer/      encrypted/versioned backup target (operator-selected)
/etc/outremer/
  outremer.env              host-managed secrets and topology, mode 0640
```

Never store mutable state or credentials under a release directory. The static
site in `site/` is a release/export seed; production pipeline output is directed
to `OUTREMER_SITE_DIR`. Until #114 moves reviews server-side, browser-local
review data must still be exported before browser storage is cleared.

## Render and inspect configuration

Rendering accepts topology only and refuses unsafe root paths, traversal, unsafe
account names, and non-loopback upstreams:

```bash
python3 deploy/tei/render_config.py \
  --public-base-path /outremer/ \
  --release-root /opt/outremer \
  --state-root /var/lib/outremer \
  --runtime-user outremer \
  --output-dir build/tei
```

Inspect the output before installing it. In particular confirm the URL prefix,
ports, runtime identity, filesystem paths, and nginx server-block context.

## Clean staging installation

1. Create the dedicated system account and approved directories. Grant the
   account read access to `/opt/outremer` and only the required write access to
   `/var/lib/outremer`; do not grant a login shell or sudo.
2. Fetch a signed tag/commit or immutable release artifact into
   `/opt/outremer/releases/v0.1.0`. Record its commit and artifact digest.
3. Create a Python 3.12 virtual environment inside that release and install from
   `requirements.lock.txt`, then install the local project without resolving new
   dependencies:

   ```bash
   python3.12 -m venv /opt/outremer/releases/v0.1.0/.venv
   /opt/outremer/releases/v0.1.0/.venv/bin/pip install -r requirements.lock.txt
   /opt/outremer/releases/v0.1.0/.venv/bin/pip install -e . --no-deps
   ```

4. Seed `/var/lib/outremer/state/site` from the release's `site/` directory on
   the first installation. On upgrades, sync application assets without deleting
   generated `data/`, `evidence/`, review exports, or other mutable artifacts.
5. Copy `outremer.env.example` to `/etc/outremer/outremer.env`, replace every
   `TBD` through the approved secret/topology process, set ownership
   `root:outremer`, and mode `0640`.
6. Render templates. Install the systemd units in `/etc/systemd/system/` and the
   nginx fragment in the approved `tei.dh.unibe.ch` TLS server block.
7. Point `current` at the release with an atomic symlink replacement, reload
   systemd, run `nginx -t`, then reload nginx.
8. Start `outremer-web.service`. Run the worker manually only after backend
   preflight; #112 will automate the live provenance gate.
9. Smoke-test `<base>/`, representative HTML/JS/CSS/data paths, the redirect from
   the missing trailing slash, and a deliberate `/api/` request. An unavailable
   future API must fail as an API request, never return the site index.

## Upgrade

1. Back up and integrity-check mutable state before migration.
2. Install the new pinned release beside the old one; never modify `current`.
3. Build its virtual environment from the lock file and run offline tests.
4. Stop the timer and wait for any active worker to finish. Do not kill an
   inference job midway unless the incident runbook requires it.
5. Apply documented, forward-compatible state migrations and record their
   version. #114 owns transactional database migrations when introduced.
6. Atomically repoint `current`, restart the web unit, run the smoke test, then
   re-enable the timer. #112 adds staging-to-production promotion and manifests.

## Rollback

Application rollback is an atomic `current` symlink switch to the immediately
previous pinned release followed by a web restart. Before switching:

- stop the timer and ensure the worker is inactive;
- check whether the release changed mutable-state schemas;
- restore the pre-upgrade snapshot if the older release cannot read the migrated
  schema; never run an old binary against incompatible newer state;
- run the same URL-prefix and representative-artifact smoke tests;
- record release digests, state snapshot, reason, operator, and timestamps.

Rehearse this procedure on staging before production promotion. Keep at least the
current and previous verified release until the backup retention policy says
otherwise.

## Backup and restore

Back up mutable state, governed source inputs where permitted, review exports,
audit/provenance records, and the release manifest. Do not back up rebuildable
caches unless recovery time requires it. Secrets use the university credential
backup process and must not be copied into research-data archives.

A backup is successful only after an automated integrity check and a periodic
staging restore. Restore into empty state paths, verify ownership/modes, validate
schemas and artifact digests, start the web service, then run an offline fixture
before permitting a live pipeline job.

RPO, RTO, retention, encryption, backup destination and restore ownership remain
blocking infrastructure decisions in #110; bots must not invent them.

## Disaster recovery

For loss of the host, rebuild a clean host from a pinned release, render reviewed
configuration, restore the latest verified mutable-state snapshot, restore
credentials through the approved channel, validate dependency routes, and run
the readiness suite from #115. DNS or proxy cutover occurs only after evidence,
decisions, provenance, and run-state integrity checks pass.

For compromise, isolate the host first, preserve logs according to policy,
rotate all service/session credentials, rebuild rather than trusting the old
runtime, and review published artifacts produced during the affected interval.

## Operator checks

```bash
systemctl status outremer-web.service
systemctl status outremer-worker.service
systemctl list-timers outremer-worker.timer
journalctl -u outremer-web.service -u outremer-worker.service
nginx -t
```

Monitoring, readiness, alert thresholds and production rehearsal are completed
by #115.
