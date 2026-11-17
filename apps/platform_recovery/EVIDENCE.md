# V10 E — local recovery evidence

Date: 2026-11-17. Base head verified through GitHub PR #228 and fetched explicitly:
`12840d54c263e63b214ce72eff1d8b4f93f9900e`.
Branch: `codex/20261117-v10-recovery`. Only `apps/platform_recovery/**` changes.
No subordinate PR, merge, production deployment or external transmission.

## Final affected-scope run — PASS

Python 3.13.5; pinned repository dependencies; PostgreSQL **17.12** Debian binaries.
Both servers were initialized as disposable local trust-authenticated synthetic
clusters using the existing helper. No installed server or real data was used.

Actual command from `/workspace/fatwa-platform`:

```sh
/workspace/fatwa-venv/bin/python -m infra.dev.with_casework_postgres \
  --pg-bin /workspace/pg/usr/lib/postgresql/17/bin --major 17 \
  --settings config.settings.campaign_review -- \
  /workspace/fatwa-venv/bin/python -m apps.platform_recovery.tests \
  --pg-bin /workspace/pg/usr/lib/postgresql/17/bin
```

Final result:

```text
SYNTHETIC_POSTGRES=postgres (PostgreSQL) 17.12 (Debian 17.12-0+deb13u1); fresh owned cluster
RECOVERY_BASELINE:
  tables: 51
  filesystem_objects: 2
  media_owner_references: 5
  casework_case: 2
  casework_caseevidence: 3
  casework_answerrevision: 2
  case_attachments_caseattachment: 1
  answer_media_privateanswerrelease: 1
Ran 19 tests in 16.495s
OK
```

The five media owner rows are one requester attachment and two retained multipart
answer revisions (two inline text rows and two filesystem audio references).
Content-addressed audio is shared safely across revisions; there are two distinct
external objects, not one object per owner row.

| Evidence | Result |
| --- | --- |
| Complete restore, reopened service process, preserved bytes/versions/approval/release | PASS |
| Staff/requester other-case denial, organizer denial, missing-authority denial | PASS |
| New facts close old restored answer; ownership and attachment mutation guards | PASS |
| Six injected restore-phase faults; reusable verified backup after failures | PASS |
| Missing/corrupt source/backup files; dump/manifest damage; incomplete snapshot | PASS |
| SHARE lock blocks concurrent SQL mutation; source row/file baseline unchanged | PASS |
| Symlinks, extra inventory, missing pin, existing target-name collision | PASS |
| Wrong rollback OID/nonce; connected consumer blocks DROP; retry after close | PASS |
| Hard process death (`os._exit(73)`) after data restore; journal rollback | PASS |
| Partial filesystem write failure; preserved target files; successful retry | PASS |
| Disabled SQL trigger and changed cross-case attachment row detected | PASS |
| Absent/new media owner schema and nondefault database policy fail closed | PASS |
| Separate newly initialized PostgreSQL server; full restore and service checks | PASS |
| Failure-journal disk-write error does not prevent identity-checked rollback | PASS |
| System checks + migration-drift checks inside restored processes | PASS |
| Ruff check, Ruff format check, staged whitespace check | PASS |

Tests are implemented in [tests.py](tests.py); the reopened process assertions are
in [verify_fixture.py](verify_fixture.py). Temporary SQL dumps, private originals,
tokens and journals were not committed. The helper stopped both disposable servers
and cleaned their owned temporary data directories after testing.

## Failures found and resolved

- A raw pg_dump schema comparison initially rejected a valid restore because
  PostgreSQL distributes varchar-array casts over literal elements when reparsing
  CHECK constraints. The comparison now canonicalizes only that equivalent literal
  form and the psql restriction nonce. SQL bodies, constraint values, owners/ACLs
  and trigger status remain included; deliberate trigger tampering is rejected.
- Initial reopened-fixture serialization included datetime objects; the synthetic
  IPC encoder was corrected. Missing authority then correctly denied private
  release access. The test now explicitly checks that denial before reattaching
  the same narrowly scoped synthetic authority and checking allowed access.
- The first independent-server restoration found timestamp fingerprints depended
  on the new server's timezone (Django's inherited timezone changed initdb's
  default). Fingerprint sessions now fix UTC/date/interval/bytea/float formats.
  The independent-server restore and full 19-test suite subsequently passed.

No successful unaffected V9 suite was rerun. Focused reruns followed the failures,
then one complete final affected-scope run established the result above.

## Integration and remaining limits

The callable/CLI freeze, snapshot, pin, restore and rollback contract is in
[README.md](README.md). The coordinator must stop writers/GC, retain the manifest
pin separately, and only reopen the application on a returned `READY` DB/root.
The module does not modify shared settings or activate a restored environment.

**NOT RUN:** PostgreSQL 18, browser-driven V10 campaign integration, production
restore, scale/load/capacity and real storage failure hardware. PostgreSQL 18
remains a required integration/CI verification if that target is claimed.
No claim is made that this component completed the whole V10 browser journey.

**Bounded behavior:** only trusted locally generated synthetic bundles, default
credential-free database profile, ordinary public tables, known V9 media owners,
and temporary private filesystem roots are supported. Identity authorities and
other external secrets/services are not copied. Other DB-level policies/locales
fail closed. Backups are unencrypted. Operator-enforced offline freeze remains
required; this is not an online maintenance subsystem or production backup plan.

**Crash window:** an abrupt death between CREATE DATABASE and durable identity
journal recording remains manual quarantine; no guessed deletion is attempted.
Post-journal crashes are exercised with a real killed process. READY targets are
never deleted by rollback. Files and failed-target evidence are preserved.

Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.
The campaign completion estimate is left to project leadership.
