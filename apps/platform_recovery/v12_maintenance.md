# V12 P0 — transaction-complete maintenance admission

Base: verified GitHub PR #230 and remote integration head
`5ecc46fbb252adc06e0e0a1cbeb129eb7fe00c64`. Branch:
`codex/20261117-v12-maintenance`. V11 branch/history preserved; no main/PR/deploy.
AGENTS.md, scope trace, owner decisions and V11 maintenance/testing contract read.
No `.agents/skills` directory exists. This is P0 only, not permission to start P1.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**
Owner reference 79% ±8 is unchanged; no acceptance or percentage claim.

## Problem and resulting behavior

V11 surrounds native transactions and synchronous on_commit callbacks correctly
for well-behaved services. Its exception path, however, could release the lease
without checking a transaction stranded by the caller; its normal exit detected
the transaction but still released without aborting it. Low-level mutation_guard
did not enforce the outer boundary. V12 applies that enforcement at the actual
filesystem lease, on both successful and exceptional exit.

- Reject caller-owned outer atomics, manual autocommit-off transactions and raw
  BEGIN before admission. Reject configured aliases other than the single default
  database; one control cannot represent multiple databases.
- Hold native commits and all synchronous on_commit callbacks under the same live
  execution-bound lease. Existing nested service/callback work may finish while
  DRAINING; new executions are denied. No automatic extra transaction is added.
- If the writer strands a transaction/callback queue, explicitly await the
  PostgreSQL ROLLBACK response and verify IDLE, then close the connection and
  discard callbacks before releasing the lease. Never commit unfinished work or
  execute its pending callbacks. A leaked atomic must still unwind in its caller;
  its raw connection is already closed. Raise `maintenance_unclosed_transaction`.
- If rollback acknowledgement or closure cannot be proved, persist the private
  `unsafe-transaction` marker and deny status/admission/freeze/resume. This is a
  fail-closed incident, not a successful snapshot. There is deliberately no marker
  deletion/reset API. Preserve the control for inspection and stop the faulty
  synthetic process; do not remove the marker to manufacture a successful cut.
- Ordinary domain/callback errors remain their original errors when no transaction
  is stranded. A completed commit stays committed if its later callback fails;
  admission does not promise application-level atomicity across multiple commits.
- Reject returned generators/coroutines/async generators from mutation_service;
  synchronous admission cannot be lent to later work. Arbitrary background work
  scheduled by custom code is unsupported and must obtain its own admission.
- GC and file conversion remain blocked FROZEN through the existing wrappers.
  The fresh-target restore file exception now permits WRITE only, never GC.
  Unknown operation labels are refused even inside nested application admission.

ACTIVE → DRAINING → FROZEN remains serialized by the existing admin/activity
locks. Snapshot holds both; resume cannot race it. Repeated enter preserves the
generation. Explicit confirmed resume with the current generation is required;
neither success, failure nor process restart resumes automatically. An explicit
cancel from DRAINING still requires all activity leases to have drained.

## Integration contract and remaining wiring

No model/schema migration, settings edit or recovery-engine change is introduced.
Owned production modules: `maintenance.py`, `integration.py`, new `admission.py`.
Only new `v12_maintenance*` tests/docs accompany them. No changes to service.py,
encrypted.py, __main__.py, rights, media, casework or shared commands.

Keep the existing `mutation_scope`, `mutation_service`, `mutation_context`,
`storage_scope` APIs and topmost `MaintenanceGuard`. All participating processes
must retain the same configured database-bound control/private root and required
flag. The compatibility flag-off path is not a maintained pilot.

New management APIs in `apps.platform_recovery.admission`:

```python
# Dispatcher hook, before calling any command body:
require_supported_command(command_name)

# Reviewed replacement for application call_command sites:
run_management_command(command_name, *args, **options)
```

The latter holds full admission through the command's native exit. The supported
set is check/showmigrations/migrate, the two Wave7 commands and the three reference
commands. Unknown commands and shell/dbshell/flush/loaddata/clearsessions/test are
denied even in ACTIVE or nested admission. Fixture/test bootstrap must occur as
the existing isolated stopped-writer setup, not as an operational bypass.

**The hook is supplied, not globally installed.** The integrator owns dispatcher
and command overrides, including direct call_command paths. It also needs the
three internal `require_admission()` checks identified in the
[exact wrapper inventory](v12_maintenance_inventory.md): answer-part cloning,
citation cloning and GET/HEAD throttle writes. That file records existing wrappers,
composed boundaries, session behavior and separately excluded SQLite stores.
Until those connections land, do not claim a fully closed P0 application perimeter.

No claim of preventing raw ORM/SQL, arbitrary Python, direct MigrationExecutor,
independent database clients or privileged DB users. Recovery capture/restore
remains its separately guarded offline operation; no source-write exemption was
added. The control is an application coordination boundary, not an OS/DB privilege.

## Focused evidence

Python 3.13.16, Django 5.2.18; fresh owned clusters via the repository helper:

| Engine | Affected verification | Result |
|---|---|---|
| PostgreSQL 17.12, Debian 17.12-0+deb13u1 | 15 new P0 + 11 existing admission integration tests | 26/26 PASS, 4.447s |
| PostgreSQL 18.7, locally built | Same 26 tests | 26/26 PASS, 3.806s |
| Both majors, subsequent new concurrency test | Pause actual rollback before its acknowledgement; enter must stay DRAINING | 1/1 PASS each |

Total **27 distinct affected tests per major**, including encrypted fresh-target
restore while source is FROZEN, GET/HEAD throttle boundaries, GC/storage conversion,
native source capture commits, migration admission, stale/copied execution contexts,
callback ordering/errors, leaked manual/raw/atomic transactions, failed rollback
poison, explicit resume/generation checks and command-hook refusal. The final
concurrency addition changed tests only; unaffected suites were not rerun.
Ruff and Django system checks passed. No browser/UI change; no new browser claim.

```sh
FATWA_TEST_PG_BIN=/path/to/postgresql/17/bin \
.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings config.settings.campaign_review -- \
  .venv/bin/python manage.py test \
    apps.platform_recovery.v12_maintenance_tests \
    tests.casework.test_v11_maintenance.MaintenanceIntegrationTests \
    --noinput --verbosity 2
# Repeat with the matching PostgreSQL 18 binaries and --major 18.
```

History retained: the first PG17 invocation omitted FATWA_TEST_PG_BIN and reported
22 passed/1 skipped; the encrypted test was subsequently run and passed, then
included in the final 26-test matrix after rollback-ack enforcement changed code.
No functional test failed. PGDG/download endpoints returned HTTP403; the Debian
PG18 binary could not run on this environment's older libc/ICU/libxml. A first
source build lacked m4. No host packages/settings were modified: matching source
and build tools were unpacked under `/tmp`, then PG18.7 built successfully with
`--without-icu --without-readline --without-zlib` for this bounded test drill.
Source: Debian `postgresql-18_18.7.orig.tar.bz2`, SHA256
`441dfae4280cae3e0425e5f876f80559fb0731c140f1aae22b3e5a54d0411bfd`.
These are local results; combined exact-head CI and the required outside-file
wiring remain the integrator's responsibility. Historical V11 evidence is unchanged.
