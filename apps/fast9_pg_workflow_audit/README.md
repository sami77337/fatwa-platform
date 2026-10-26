# FAST9 persisted workflow audit boundary

Base: FAST8 Draft PR #151, `0769f66e93fdf710ca55e9e68e87430a93f14c40`.
Lane: `codex/20261027-fast9-pg-workflow-audit-pc1`; PR target:
`codex/20261026-fast8-integration-pc1`. Only the three FAST9 lane folders change.

`adapter.read_stored_audit` connects the **existing**
`apps.intake_workflow.review.load_review_worklist` to the existing
`workflow_audit` serializer and provenance projection. The workbench's
`persisted.stored_audit` established the read composition but does not require a
caller-pinned DB OID, source/row hashes, latest review identity or audit window.
This technical adapter adds those boundaries without changing that view.

It has no URL, model, migration, write call, seed, fixture fallback, role or grant.
No mount or settings/CI/dependency edits are needed. There is no public endpoint.

## Identity and limits

- Supply exact test database name **and OID**, batch UUID, row UUID and ordinal,
  source payload SHA-256, original UTF-8 row SHA-256, latest event UUID,
  operation UUID and audit-window SHA-256. External IDs never select/join records.
- The existing Wave7 synthetic-read gate must be enabled. Configuration checks
  reject base/default-live DBs before connecting. The supplied disposable name
  must exactly equal `WAVE7_TEST_DATABASE_NAME`; actual role, OID and PostgreSQL
  read-only session are checked before reading any stored records. The existing
  Wave7 ownership/version/schema guard then runs unchanged.
- The existing Wave7 guard requires `FATWA_WAVE7_SYNTHETIC_WRITES=1` even for
  reads; this adapter never obtains a write tag or opens a write unit of work.
  The command forces `default_transaction_read_only=on` at connection startup.
- Source bytes/slices are validated by the real Wave7 reader. The adapter adds
  exact source hash and selected row identity/span checks. Latest event and
  operation IDs must match, and latest review status must equal the stored row.
- One selected row, at most 100 review events and 100 current references are
  returned. The reader is invoked with page size 1. Unrelated page rows/batches
  are discarded from the result and fingerprint. No strings, Unicode, CRLF,
  event IDs, timestamps or original DTO objects are rewritten.
- `window_sha256(previously_supplied_worklist)` computes the deterministic pin
  with the existing audit serializer. This pure helper proves **no persistence**.
  Obtain that DTO and the remaining pins only from the authorized synthetic
  harness that supplied the stored case. This command does not discover them.
- Wave7 guards require autocommit reads. Two bounded observations must match the
  caller's pin and each other, followed by another DB identity check. This is
  optimistic change detection, **not** a transactionally consistent snapshot;
  concurrent changes after the final observation remain possible. No complete
  historical audit claim is made, including when `events_truncated` is false.

The stored schema/DTO has **no exact draft revision link**. Passing
`draft_revision` returns `NOT_CONNECTED / EXACT_REVISION_LINK_UNAVAILABLE` before
DB access. No row position, external ID, event order, timestamp, status or audit
hash is promoted to a draft revision number. `revision_connection` and
`permission_connection` remain `NOT_CONNECTED` even for a successful technical
read. Source-owner, catalog and policy acceptance remain unestablished.

Missing state/identity and disabled gates return `NOT_CONNECTED`. Unavailable
read prerequisites or unexpected DB/parser/driver errors return `NOT_RUN` with
fixed redacted reasons, no partial DTO or invented saved events.

## Offline execution and observed results (Windows, Python 3.13.15)

Run from the repository root:

```powershell
python -B -m tools.fast9_pg_workflow_audit.offline
python -B -m tools.fast9_pg_workflow_audit.offline --affected
python -m ruff check apps/fast9_pg_workflow_audit tests/fast9_pg_workflow_audit tools/fast9_pg_workflow_audit --no-force-exclude
python -m ruff format --check apps/fast9_pg_workflow_audit tests/fast9_pg_workflow_audit tools/fast9_pg_workflow_audit
git diff --check
```

Results: **25 new tests PASS**, **58 existing affected tests PASS**, zero skips,
xfails, failures or errors in the final runs. Django system checks: no issues.
Ruff lint/format and diff whitespace checks pass. The runner strips inherited
DB/credential variables, uses unreachable port 1, and never sets up a database.

New input fixture: `tests.fast9_pg_workflow_audit.test_adapter.sample()`, a
hand-built **in-memory synthetic DTO**, UUID batch 1 / row 2 / event 3 /
operation 4, fixed timestamp `2026-10-27T08:12:13.456789+00:00`, exact Arabic
row with CRLF. Its source hash `a` repeated 64 times is an explicit mocked
boundary sentinel, **not a tested persisted payload SHA**. No source archive is
used. Affected tests use their existing synthetic DTO/contract fixtures only.

The first affected-suite run produced **15 error entries** because the new
offline runner omitted Django's test-environment setup (`response.context` was
None). The runner now calls setup/teardown; rerunning the same 58 tests passed.
The initial format check found six files needing formatting; those were fixed.
No assertion was weakened, skipped or xfailed.

## Opt-in existing-state PostgreSQL acceptance

**NOT_RUN in this lane execution:** no preauthorized disposable DB name/OID,
connection profile, or stored synthetic review identity was supplied. No DB or
credential search, initialization, migrations, creation or data writes occurred.
Browser: NOT_RUN (no UI added). Owner archives: NOT_RUN.

The following command requires an already supplied synthetic test database and
stored case, provisioned outside this lane only by the trusted existing Wave7
test harness. Its existing schema must already be present. Never substitute a
live/base DB, run a new initializer, or create reviews to satisfy this command.
Wave7's trusted runner normally deletes its test DB on teardown, so the supplying
harness must run this read while its authorized test DB is still available.

Use an already authorized `config.settings.wave7_test` environment with explicit
`PGHOST=127.0.0.1`, supplied `PGPORT`, `PGUSER=wave7_synthetic`, `PGDATABASE`
set to the harness's Wave7 base name, and `PGTESTDATABASE=test_<base name>`.
`FATWA_PRODUCTION=0` and the existing Wave7 read/write guard flags must already
be set. Credentials, if required, come only from that supplied test profile.
The CLI validates this profile **without connecting to the base**, switches its
fresh connection to the explicitly supplied test name and makes it read-only.
It refuses an existing connection and does not change persistent configuration.

In PowerShell, after the harness has supplied the following identity variables:

```powershell
python -B -m tools.fast9_pg_workflow_audit --synthetic-only --acceptance `
  --database-name $env:FAST9_TEST_DB --database-oid $env:FAST9_TEST_OID `
  --batch-id $env:FAST9_BATCH_ID --row-id $env:FAST9_ROW_ID `
  --row-ordinal $env:FAST9_ROW_ORDINAL --payload-sha256 $env:FAST9_PAYLOAD_SHA256 `
  --row-sha256 $env:FAST9_ROW_SHA256 --latest-event-id $env:FAST9_EVENT_ID `
  --latest-operation-id $env:FAST9_OPERATION_ID --audit-sha256 $env:FAST9_AUDIT_SHA256
```

The seven existing-state acceptance tests check exact reads and SELECT-only
queries (budget <120 statements), wrong DB OID, source/row hash mismatch,
cross-case row substitution, stale event/audit, disabled gate with no SQL and
missing exact revision links. They run only after a positive pinned read, using
`unittest.TestResult` with no setup/flush/teardown/migration. No skips are allowed.
Exit 0 = successful bounded read (and acceptance PASS if requested), 1 = actual
acceptance failure, 3 = NOT_RUN/NOT_CONNECTED; argparse errors exit 2. Output
contains status, fixed reasons and counts, never stored source/event text.

The shared B6/C6/D6 suites do **not** automatically collect these new modules;
green inherited CI is not FAST9 test coverage. See the Draft PR for exact tested
commit SHA, independent read-only review and actual remote CI results.

Gate B **NOT_PASSED**; C/D/E **HOLD**; Phase01 **BLOCKED**;
**SCOPE_DEVIATION_HOLD / NOT_DEPLOYED / GATES_HOLD**;
U03/U10 **OWNER_APPROVAL_PENDING**. No merge, deployment or approval inference.
