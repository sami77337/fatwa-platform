# A6 execution record — 2026-10-15

NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED.
No commit, push, PR, merge, deployment, account, grant or publication.

Base code SHA: d7b6dc1e4d50b87a88cca036a6025352ecc0ccbe.
This SHA does not include the uncommitted integrated source or A6 edits.
A6 wrote only tools/dev, tests/dev, docs/operations/A6_LOCAL_OPERATION.md,
and docs/dev/a6. Pre-existing integration changes elsewhere were left as found.
S5 infrastructure files/docs were not available in this copy; no sibling copy
was read or modified.

## Implemented

- Fixed-action Windows buttons for start, restart, status, health, regressions,
  and explicitly disabled database tests. A successful start/restart opens the
  local catalog; all buttons preserve their exit status and review window.
- Separate lifecycle/health/regression reports under tools/dev/.local, atomic
  replacement, exclusive owner-token locks and actionable private errors.
- Local-only Docker transport and exact-object inspection. Start/restart require
  THIS worktree's read-only code mount, known database/role/settings, safe existing
  command and expected internal/loopback topology. Only the named site can be
  started/restarted; database lifecycle is untouched.
- GET-only fixed-loopback HTTP checks with no proxy/auth/redirects, bounded
  responses, deadlines, edition/source-kind guards and bounded catalog probes.
- Source archive/member/mapped pins and idempotent original-title/persistence
  comparison retained. Source apply and the legacy Django --keepdb path disabled.
- Separate SELECT-only test-target preflight and six pure Python guard tests.
  Neither launches Django tests or provisions anything.

## Actually executed

| Check | Observed result |
| --- | --- |
| Real HEALTHCHECK_LOCAL.cmd, browser/pause disabled only in its child environment | Exit 0; PASS, 14/14 checks. |
| Real STATUS_LOCAL.cmd | Exit 1; DOCKER_PERMISSION_DENIED; independent HTTP health PASS. |
| Real START_LOCAL.cmd, browser/pause disabled only in its child environment | Exit 1; DOCKER_PERMISSION_DENIED; independent HTTP health PASS; no container mutation requested. |
| Real TEST_LOCAL.cmd | Exit 0; 55 Node tests: 53 pass, 0 fail, 2 skipped. |
| Actual invocation of each of the six CMD buttons from a spaced/metacharacter path, using a stub host.mjs | PASS: exact fixed action received and failure exit 7 propagated. These are wrapper tests, not real container operations. |
| Node CLI help, invalid arguments and test-db | Help exit 0, invalid arguments exit 2, database-test action exit 1 / NOT_RUN. |
| PowerShell AST parsing | PASS without changing execution policy. |
| Actual PowerShell script invocation from a spaced/metacharacter path | SKIPPED: host execution policy disables .ps1 execution. |
| Python guard unit tests via py -3.13 -B -m unittest discover -s tests/dev -p test_db_guard.py -v | NOT_RUN: launcher exit 112, No installed Python found. No installation attempted. |
| node --check on host/local/health/verify-live and three dev test modules | PASS for all seven files. |
| git diff --check limited to A6-owned paths | PASS, no output; most integrated files are pre-existing untracked files, so an additional direct A6 text scan covers them. |

The two Node skips are the existing optional original-archive identity test
(archive not available at its legacy path in this copy) and actual .ps1 execution
(host policy). Mock Docker/HTTP tests are explicitly synthetic. Real wrapper
invocation tests use a stub application and do not contact Docker or HTTP.

Live checks observed 200 for /, /fiqh, /fiqh?basic=1, /healthz, /readyz,
/api/v1/status and bounded books/roots/node/children/search requests in all three
modes. The limit=101 negative request returned 400. No POST, PUT, PATCH, DELETE
or external-origin request was sent by the health workflow.

The live edition metadata reports 11,397 headings, 32 roots and maximum depth
five. The bounded roots response actually contained 32 root nodes. Archive and
member hashes reported by the API matched the pinned book-622 identity:

- ZIP: FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip
- ZIP SHA256: 82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce
- JSONL member: FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl
- Member SHA256: 37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14
- Retained mapped pin: b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7

These are live API metadata observations. A6 did not independently rehash the
archive, recompute the full mapped checksum, query SQL directly, or compare all
11,397 stored rows. Earlier README/host import evidence is preserved and is
not counted as a newly executed A6 acceptance test.

## Still unverified or intentionally disabled

Actual container startup/restart and current container/worktree/network topology
could not be verified because access to Docker was denied. The runner refuses
a container mounted from the original integration or another agent's copy;
live HTTP success does not establish that this A6 copy is serving the port.
Automatic browser opening after successful real startup was not exercised.

Django/PostgreSQL tests, test-target preflight against any actual candidate,
Python guard test execution, exhaustive source/database acceptance and
browser/mobile/keyboard acceptance are NOT_RUN. No database was created,
migrated, reset, imported, dropped, flushed or repaired. No credentials were
printed or overwritten. No new ports or Docker network access were enabled.

[Operation instructions](../../operations/A6_LOCAL_OPERATION.md).
[Machine-readable evidence](evidence.json).
