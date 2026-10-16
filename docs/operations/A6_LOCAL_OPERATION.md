# A6 local operation for the integrated public site

NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD. Gate B NOT_PASSED;
C/D/E HOLD; Phase01 BLOCKED; U03/U10 OWNER_APPROVAL_PENDING.

Open a button in tools/dev from Windows Explorer. Node.js and access to the
existing local Docker Desktop engine are the only launcher prerequisites. Host
Python and PowerShell script execution are not needed by these buttons.

| Button | Behavior |
| --- | --- |
| START_LOCAL.cmd | Validate the existing topology; start only fatwa-site-v1 if stopped; wait for readiness, run health checks, and open the local catalog after success. |
| RESTART_LOCAL.cmd | Validate the same topology; restart only fatwa-site-v1; wait, check, and open the catalog after success. |
| STATUS_LOCAL.cmd | Read-only Docker inspection plus live HTTP evidence. |
| HEALTHCHECK_LOCAL.cmd | GET-only loopback HTTP checks; works even when Docker access is denied. |
| TEST_LOCAL.cmd | Offline Node launcher regressions, including mocked HTTP/Docker and real Windows wrapper invocation with a stub application. |
| TEST_DATABASE.cmd | Report NOT_RUN and exit 1. Django database tests are deliberately disabled until isolation can be proved. |

The window stays open for review. START/RESTART open
http://127.0.0.1:8000/fiqh only after all checks pass. Buttons have fixed actions
and do not forward extra command-line text. For automation, set FATWA_NO_PAUSE=1
and FATWA_NO_BROWSER=1 in the caller environment. These switches do not relax
any container, database, credential, or network guard.

The equivalent developer command is node tools/dev/host.mjs ACTION, where ACTION
is exactly one of start, restart, status, healthcheck, test, test-db. No action
means start. --help prints usage without Docker/HTTP access. Extra arguments,
custom containers, addresses, ports, sources, credentials, and import/migration
actions are rejected. Exit codes: 0 PASS/help; 1 failed/blocked/NOT_RUN operation;
2 invalid CLI arguments or missing Node in a button.

## Container scope and startup prerequisites

The only lifecycle target is the existing fatwa-site-v1 container. The runner
inspects that exact name, fatwa-s5-dev-pg18-postgres-1, and the existing
fatwa-s5-dev-pg18_local network. It does not enumerate unrelated containers.
The database must already be running and healthy; this runner never starts,
restarts, creates, removes, or repairs the database.

Before a site start/restart, validation requires:

- Docker Engine 28+ over a local named pipe or Unix socket. Remote Docker
  transports are rejected before contacting any daemon.
- PostgreSQL 18.6 with the expected S5 labels on the internal local network;
  existing DB publication, if configured, is only 127.0.0.1:55432.
- The site's sole published port is 127.0.0.1:8000, with no host/shared networking
  or privileged container. Existing network attachments must match the expected
  bridge plus internal database network. No network setting is changed.
- THIS A6 workspace mounted read-only at /app or /site, plus exactly the existing
  read-only application credential mount at /run/secrets/app-password.
- fatwa_app / fatwa_reference on the inspected database container, development
  settings, no Docker-environment password or DATABASE_URL, and no production mode.
- An existing Django runserver command without import, migration, reset or other
  database maintenance. Network fetch commands and online pip installs are refused.

A container mounting the original integration/site-v1 or another agent's copy
fails with WRONG_WORKTREE_MOUNT. The runner will not rebind, recreate, copy into,
or restart it. A passing HTTP check alone does not prove which worktree is serving
the port. If this exact A6 container configuration is unavailable, launch/restart
remain blocked while read-only HTTP checks can still succeed.

The existing host.mjs now delegates operation to local.mjs. Shell-free argument
arrays preserve spaces and metacharacters in paths. The optional site.ps1 adapter
uses the PowerShell call operator and argument arrays; it never changes execution
policy. Start/Serve, Restart, Status, Check/Healthcheck, RegressionTest and
Test/TestDB map to the guarded actions. Its old migration/source actions fail
before any Python/database operation.

## Health evidence and privacy

health.mjs uses the native Node HTTP client with a fixed 127.0.0.1:8000 target,
GET only, no proxy, credentials, cookies, redirect following, or port discovery.
Each response has a 512 KiB limit and a four-second total deadline. Every API
page is bounded to 20 or 100 records. The deliberate limit=101 request must
return 400 and is not an unbounded data request.

The health check covers /, /fiqh, SSR fallback, /healthz, /readyz, public status,
edition inventory, all 32 roots, one root detail and child page, three original-title
search modes, and invalid-limit behavior. It checks Arabic/RTL HTML, source kind,
edition consistency, disabled sensitive/publication flags, and readiness JSON.

Reports separate HTTP behavior from live API source metadata (11,397 headings,
32 roots, depth five and expected archive/input hashes). The numbers and hashes
are what the API reports. This is neither an independent source-file checksum
verification nor an exhaustive comparison of all stored rows. Unit tests,
Django/PostgreSQL tests and browser/keyboard/mobile acceptance are separate.

Raw Docker/process errors, environment values, response bodies, titles/search
queries and secret contents are omitted from action reports. Inherited database
credentials, Django settings, production flags and Node startup hooks are removed
from child environments. Credential files are never generated, replaced or
read by the Node lifecycle runner.

## Reports and interrupted launches

Each action atomically replaces only its own ignored report:

tools/dev/.local/a6-ACTION-result.json

The reports include the base Git SHA, a statement about local edits, and a hash
of the workspace path. They do not overwrite the historical .local/host-result.json
or its prior import evidence. The test action reports Node totals separately.

Start/restart use tools/dev/.local/operation.lock. A second launch fails without
touching the first lock. Only the lock's owner token can release it. After an
interrupted process, inspect the recorded PID and close/verify the earlier run
before manually removing that exact stale lock. The runner does not guess whether
a stale-looking lock is safe to remove.

If Docker is missing, unavailable, denied, or an exact object is missing, the
report gives a fixed actionable error and a nonzero exit code. Independent live
HTTP evidence is still collected. A healthy website cannot turn a failed
container operation into PASS.

## Source and database protection

This A6 workflow supersedes the initial-import launcher description in the root
README for this copy. No ordinary button or action invokes import_book622,
migrate, Django test setup/teardown, a Docker worker, pip, or credential setup.

The retained container_workflow.py --verify-source comparison keeps the original
S1 archive/member/mapped checksum validation, original-title checks, hierarchy
checks, application-role restrictions, explicit read-only transactions and
idempotent unchanged-snapshot comparison. It refuses an absent or conflicting
snapshot. Source apply and the old Django --keepdb test path are disabled. This
separate source comparison was not executed during A6 work.

Pinned identity:

- ZIP: FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip
- ZIP SHA256: 82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce
- Member: FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl
- Member SHA256: 37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14
- Mapped SHA256: b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7

A test_ database name, emptiness check and --keepdb do not prove isolation from the
current cluster or prevent Django migrations, fixture loads, flushes and teardown.
For that reason no Django database test command is launched or generated as an
automatic follow-on.

db_test_guard.py --preflight is separate read-only candidate tooling. It first
rejects the live database/role, protected ports, non-loopback targets, inherited
DSNs/credentials/service options and ambiguous names. A candidate must use a
test_fatwa_a6_ followed by 12 lowercase hexadecimal digits name, fatwa_a6_test,
another explicit loopback port and an explicitly supplied test-only credential
file. No live credential fallback exists. Connection startup forces read-only
transactions and short timeouts. Its SELECT-only preflight checks actual
database/role/version identity, a separate empty cluster without fatwa_reference
or other application databases, and absence of administrative role privileges.
Even successful preflight reports Django tests NOT_RUN; it does not create,
migrate, flush, drop, grant, or run tests.

Pure Python guard tests are runnable with Python 3.13 without Django/psycopg:
py -3.13 -B -m unittest discover -s tests/dev -p test_db_guard.py -v
They use synthetic connection objects and do not contact PostgreSQL.
Node regressions are runnable with TEST_LOCAL.cmd, or
node --test --test-reporter=tap tests/dev/*.test.mjs.

Read [the A6 execution record](../dev/a6/RESULT.md) for actual results and limits.
