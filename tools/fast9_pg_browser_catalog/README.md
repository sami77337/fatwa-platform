# FAST9 protected operator/browser + disposable PostgreSQL catalog acceptance

Development-only acceptance harness, based independently on FAST8 Draft PR #151,
SHA `0769f66e93fdf710ca55e9e68e87430a93f14c40`. No shared routes/settings/CI,
dependencies, application services, source files or migrations are changed.
The operator uses the actual integrated `/dev/operator-navigation` mount.

## What executes

`python -B -m tools.fast9_pg_browser_catalog.run` starts a loopback Django WSGI
server and two actual protected Chrome journeys: the new integrated operator
journey and the existing FAST8 browser conformance script. Both use existing
domain fixtures/services; no copied source rows, catalog doubles or route mocks.
The browser-only path forbids every Django connection attempt, regardless of
`FAST8_EXISTING_SYNTHETIC_PG`. Its research journey uses the existing unjoined
history case; it cannot claim a PostgreSQL source connection.

The guarded `--postgres` path additionally:

1. Requires every exact explicit CI authorization below **before connection**.
   Rechecks configured and actual database identity, existing Wave7 ownership,
   PostgreSQL 17/18 and absence of other database sessions. Rejects unknown schemas,
   relations/sequences, nonempty domain tables and any pre-existing test DB.
2. Uses only the existing `tests.wave7_foundation.runner.Wave7TestRunner` lifecycle
   to create a fresh test database, claim its empty identity and run existing
   migrations. Never initializes/migrates the base, reuses a test DB, or force-drops
   a resource. The trusted runner checks actual identity/emptiness before its first
   ownership-table write. After migrations the seven domain tables must be empty.
3. Calls the existing guarded `seed_reference_catalog(synthetic_fixtures_only=True)`
   and FAST8 exact catalog preflight. A failed pin/inventory match never becomes PASS.
4. Verifies keyboard navigation and RTL layout at **320/375/1280**; operator to
   historical workbench preserves revision and source hashes; operator to research
   to catalog carries edition 7001. All three node API responses are compared
   exactly at each width. FAST8 also verifies queue/search/triage/export links,
   original CRLF/Arabic source bytes, source digests and historical packet identity.
5. Denies foreign origins and POST/PUT/PATCH/DELETE before browser network dispatch.
   Every new WSGI DB connection checks actual name/role and enables PostgreSQL
   `default_transaction_read_only`; actual HTTP denial tests separately exercise
   application middleware. No browser write request is sent to PostgreSQL.
6. Compares hashes of all public table rows (including original timestamps), sequence
   state, columns/defaults, constraints and triggers before/after browsing. These are
   final-state checks, not an audit log of every SQL statement. Closes browser trees,
   profiles, WSGI thread and connections, delegates drop to the trusted runner, then
   checks the exact test DB is absent and the base fingerprint unchanged.

Result is PASS (exit 0) only if browser, catalog, unchanged-data and teardown stages
all pass. Failed execution/cleanup is FAIL (exit 1). Missing or denied prerequisites
are NOT_RUN (exit 2). Browser-only PASS remains a separate field while the overall
result is NOT_RUN. An invalid child report/exit code cannot manufacture PASS.

## Commands and measured local results

Python 3.13 with repository dependencies, Node and an existing sandboxed Chrome
are required. `FATWA_FASTBUILD_BROWSER` may point to the installed Chrome; no browser
is installed and no browser security flags are weakened by this lane.

```powershell
python -B -m unittest tests.fast9_pg_browser_catalog.test_guards -v
node --test tests/fast9_pg_browser_catalog/policy.test.mjs
python -B manage.py test tests.fast9_pg_browser_catalog.test_http tests.fast8_browser_conformance.test_conformance --settings=config.settings.test --verbosity=1
python -m ruff check tools/fast9_pg_browser_catalog tests/fast9_pg_browser_catalog
python -m ruff format --check tools/fast9_pg_browser_catalog tests/fast9_pg_browser_catalog
git diff --check
python -B -m tools.fast9_pg_browser_catalog.run
python -B -m tools.fast9_pg_browser_catalog.run --postgres
```

Measured on Windows, 2026-10-27:

| Command scope | Actual result |
| --- | --- |
| New Python guard/lifecycle tests | 22 PASS, zero skips |
| New Node request-policy tests | 3 PASS, zero skips |
| New HTTP + affected FAST8 Django modules | 16 PASS = 3 new + 13 inherited; zero skips |
| Nested inherited Node policy regression | 20 PASS, not additional new Python tests |
| Ruff check/format and whitespace | PASS |
| New harness, default mode | Both real Chrome journeys and browser cleanup PASS; catalog NOT_RUN; overall NOT_RUN, exit 2 |
| New harness, `--postgres` | NOT_RUN, exit 2, `EXACT_DISPOSABLE_CI_AUTHORIZATION_REQUIRED`; no DB connection attempted |
| PostgreSQL creation/migration/seed/read-only/fingerprint/drop | NOT_RUN locally; no authorized exact disposable service supplied |

The first runs used the base SHA above plus dirty owned paths; the harness emits
`tested_sha` and `owned_paths_dirty` on every run. Exact committed-run evidence and
remote head belong to the Draft PR, avoiding a self-referential README commit hash.
Offline lifecycle fault injection is explicitly not PostgreSQL acceptance.

Initial failures, corrected before delivery: browser-only operator research first
used `intake-1`, which correctly hit the forbidden connection guard (changed to the
already unjoined history case only in browser-only mode); a test cleared PATH and
could not run Git (metadata is now stubbed in that authorization unit test); a
misplaced concurrency test block was corrected; Ruff import ordering was fixed.
Independent read-only review also caught an overbroad relation inventory, inconsistent
child-result acceptance, a configured-identity check occurring too late, and an
incorrect assumption that UUID workflow PKs have sequences. All were corrected;
positive tests use actual model metadata as well as negative fault injection.

## Guarded opt-in PostgreSQL command

For a coordinator-preauthorized, exclusively disposable CI service only. The
existing trusted Wave7 CI lifecycle must already have provisioned an owned/migrated
**empty-domain base** named `wave7_synthetic_fast9_browser_ci`; the test DB must not
exist. This command deliberately cannot bootstrap a missing base, discover a server,
copy credentials, or accept a developer/user DB. Do not use local development
credentials. CI supplies its own synthetic-only credential and explicit service port.
No `DATABASE_URL`, `PGSERVICE`, `PGSERVICEFILE`, `PGHOSTADDR`, `PGPASSFILE` or
`PGOPTIONS` override is accepted. Missing prerequisite means NOT_RUN, not permission
to provision a new service outside the existing trusted lifecycle.

```powershell
# Only in the preauthorized disposable CI job, with PGPORT and the CI-only
# authentication already supplied by that job. These flags do not provision a DB.
$env:FAST9_SYNTHETIC_PG = '1'
$env:FAST9_DISPOSABLE_DATABASE = 'test_wave7_synthetic_fast9_browser_ci'
$env:CI = 'true'
$env:FATWA_PRODUCTION = '0'
$env:FATWA_WAVE7_SYNTHETIC_WRITES = '1'
$env:PGHOST = '127.0.0.1'
$env:PGUSER = 'wave7_synthetic'
$env:PGDATABASE = 'wave7_synthetic_fast9_browser_ci'
$env:PGTESTDATABASE = 'test_wave7_synthetic_fast9_browser_ci'
$env:DJANGO_SETTINGS_MODULE = 'config.settings.wave7_test'
python -B -m tools.fast9_pg_browser_catalog.run --postgres
```

To run the separate DB-free command in another process/session, use
`DJANGO_SETTINGS_MODULE=config.settings.test` (or leave it unset). An inherited
Wave7 settings module is rejected in browser-only mode. Run commands separately;
do not mask the overall NOT_RUN exit code to make CI green.

## Input identity, remaining connections and governance

Existing fixture: `wave7-synthetic-toc/7001/rows-1-2-3`, namespace
`wave7-synthetic-toc`, archive SHA `a` repeated 64, input SHA `b` repeated 64,
ingest checksum `c` repeated 64. These are fabricated pins, never owner-source proof.
The unchanged existing export fixture SHA256 is
`17d54614349d20488344d2c6d432823d1d8ecb46d34c90f68d129084458725e9`.
No ZIP/source archive is supplied, opened or copied.

Revision timestamps remain NOT_SUPPLIED. The research link is explicitly case-level;
it is not a historical-revision source join. Unknown/sibling/policy connections stay
NOT_CONNECTED. Source-owner/catalog-policy/production acceptance remains NOT_RUN.
Synthetic success does not alter any governance gate.

Existing B6/C6/D6 workflows are inherited and do **not** collect these new modules.
Green inherited CI is **not new FAST9 test coverage**. A coordinator must explicitly
wire the above commands and provide the exact disposable service before full PG
acceptance can execute. This lane makes no shared route/CI edits.

One independent read-only agent reviewed the final code and reran the offline
guard/HTTP/Node suites; no blocking code findings remained after fixes. The reviewer
did not claim a PostgreSQL/browser run of their own.

NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING. No real identities, user/private records, scholarly
answers/approval/publishing, public writes, schema changes, production work or merge.
