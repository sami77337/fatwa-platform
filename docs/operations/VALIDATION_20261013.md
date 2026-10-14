# S5 local validation — 2026-10-13

**NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD**

This is the original validation record. See [the 2026-10-14 publication repair record](PUBLICATION_REPAIR_20261014.md) for current scanner, test and runtime outcomes.

Branch: codex/s5-infra-ci-20261013

Actual unchanged HEAD: 08f9e25e8ada9af56561d815f74b2c7ec9ba7ead

Environment: Windows PowerShell workspace; validation commands were executed through the available local Node runtime after the standard shell tool failed to create a process. Node CLI is v24.16.0; Docker client is 29.6.1 (build 8900f1d); standalone Compose is 5.1.4. A running Docker server version was not obtained.

Read before implementation: AGENTS.md, docs/coordination/PARALLEL_EXECUTION_20261013.md, and _codex_input/queued_issue_6.md. The supplied issue is #6. The user prohibited commit/push/PR/merge/deploy/secrets; those instructions take precedence over the historical runbook delivery text.

## Actual outcomes

| Check | Result | Meaning |
| --- | --- | --- |
| Node infrastructure regression tests | PASS — 22 tests, 0 failed, 0 skipped | Unit/config/filesystem/command-planning tests; Docker calls in planning tests are mocked |
| Infra boundaries and workflow JSON/YAML parsing | PASS | Not a substitute for GitHub execution or actionlint |
| JavaScript syntax | PASS — all five module files | Actual node --check |
| POSIX shell syntax | PASS — all three scripts | Actual Git for Windows sh.exe -n |
| Actual Compose config validation, 18 and 17 | PASS, exit 0 | Both emitted a Docker config access warning; no daemon is required for this syntax check |
| PostgreSQL 18 synthetic smoke attempt | FAILED at Docker preflight, exit 1 | Database readiness/persistence/ACL/backup/restore NOT_RUN |
| PostgreSQL 17 synthetic smoke attempt | FAILED at Docker preflight, exit 1 | Database readiness/persistence/ACL/backup/restore NOT_RUN |
| S0 application detector | Correct explicit NOT_RUN, exit 0 | manage.py absent; no application checks were executed |
| Python/Django lint, format, types, system checks, migration checks, integration tests | NOT_RUN | Python and S0 foundation/dependencies unavailable |
| Dependency vulnerability audit | NOT_RUN locally | Python/pip-audit unavailable; configured in CI, not executed here |
| actionlint and GitHub Actions workflow execution | NOT_RUN | Go/actionlint unavailable; no workflow was published or triggered |
| Original owner ZIP/source acceptance | NOT_RUN | Original files not supplied to this lane; no import tested |
| Tracked-file diff and whitespace check | PASS | All previously tracked files remain unchanged; new files separately inspected |

## Input fixture and artifact identity

The runtime smoke fixture is s5-synthetic-v1: exactly two artificial rows defined in infra/dev/smoke.sh. No book text, private case, requester, user, or source ZIP data were used. Infrastructure unit tests use temporary artificial files/strings beneath ignored infra/dev/.local and mocked Docker/application commands. These tests do not prove PostgreSQL ran.

| Local input/artifact | SHA256 |
| --- | --- |
| infra/dev/smoke.sh | d505dd4bf9ef2f2dba306a0b2d39ff1fafacf8abbf4f2639254f57187ce9e3ad |
| infra/dev/tests/infra.test.mjs | 9c614611167b08a00a9c95385f76b3905044a230a94dcbf2d8e77e3b88fea48e |
| infra/dev/compose.pg18.yaml | 16d84a0917ab962864c528fdf7ecd9e8d9a386f146196df1153bdf9c72fffeb9 |
| infra/dev/compose.pg17.yaml | c4cf1a9c794a06d4185b128a2b404196a3210f1c4853c415db1bb623b57860a1 |
| .github/workflows/s5-ci.yml | 52b22b159c00160ad3227f2d55d2530b427385de32a72156d2e99a0d9cc6b1f2 |

No PostgreSQL image digest or running PostgreSQL version is available from this host. Future real smoke runs print Git HEAD, the smoke fixture hash, pulled image identity, and server version before reporting a runtime pass.

## Literal final command records

Each record contains the executable and argument vector used, exit status, and literal stdout/stderr. Empty output is shown as (empty), a transcript marker rather than command output.

### Infra regression tests

~~~text
{"executable":"node","arguments":["--test","infra/dev/tests/infra.test.mjs"]}
exit: 0
stdout:
✔ repository infrastructure and workflow boundary validation (9.1459ms)
✔ PostgreSQL 18 rejects exposure, trust auth, privileged containers, and foreign volumes (3.6384ms)
✔ PostgreSQL 17 rejects exposure, trust auth, privileged containers, and foreign volumes (2.0725ms)
✔ separate PostgreSQL 18 and 17 persistence targets and project names (2.0449ms)
✔ reject unsupported major, privileged ports, extra env settings, and shell content (0.4697ms)
✔ Docker endpoint guard refuses remote engines before any daemon operation (0.2925ms)
✔ preflight resolves local context and supports standalone Compose without shell parsing (0.1262ms)
✔ prepare refuses overwriting existing env and partially prepared credentials (7.3245ms)
✔ prepare creates only ignored credential files and does not replace them (7.0282ms)
✔ git ignores local credentials and smoke output but includes the example env (30.6571ms)
✔ development teardown command is namespaced; the CLI has no general volume-delete option (44.4237ms)

✔ smoke uses a fresh project with no ports and cleans up that project on verification failure (7.4312ms)
✔ smoke cleanup refuses a development project, external volume, or forged label (5.7352ms)



✔ smoke verifies records after forcing container recreation (5.124ms)
✔ pre-S0 detection explicitly returns unavailable; app-present/contract-missing fails closed (2.057ms)
✔ the example contract cannot activate CI and active contracts require committed input (4.2547ms)
✔ contract rejects traversal, shell executables, writable format, and writable migration stages (3.2459ms)
✔ application checks bind to the disposable CI database and never bootstrap credentials (0.6642ms)
✔ workflow rejects write permissions, unpinned actions, unsafe triggers, and unguarded app checks (1.8515ms)
✔ prepare refuses a symlinked local directory before writing any credential file (3.8502ms)

✔ smoke cleanup errors preserve the verification failure and generated files for diagnosis (5.7064ms)
✔ preflight refuses an old Docker daemon before publishing a loopback port (0.1772ms)
ℹ tests 22
ℹ suites 0
ℹ pass 22
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 218.0038
stderr:
(empty)
~~~

### Infra/workflow boundaries

~~~text
{"executable":"node","arguments":["infra/dev/checks.mjs"]}
exit: 0
stdout:
PASS: Compose boundaries, CI JSON/YAML syntax and guards, ignored paths, SQL role defaults, pinned CI dependencies.
stderr:
(empty)
~~~

### Compose JSON boundary validation

~~~text
{"executable":"node","arguments":["infra/dev/dev.mjs","validate"]}
exit: 0
stdout:
PASS: both Compose documents parse and satisfy infrastructure boundaries.
stderr:
(empty)
~~~

### S0 detection

~~~text
{"executable":"node","arguments":["infra/dev/application.mjs","detect"]}
exit: 0
stdout:
NOT_RUN: application lint/format/type/system/migration/PostgreSQL tests/dependency audit — manage.py absent; S0 has not been integrated
stderr:
(empty)
~~~

### JS syntax dev.mjs

~~~text
{"executable":"node","arguments":["--check","infra/dev/dev.mjs"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### JS syntax application.mjs

~~~text
{"executable":"node","arguments":["--check","infra/dev/application.mjs"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### JS syntax checks.mjs

~~~text
{"executable":"node","arguments":["--check","infra/dev/checks.mjs"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### JS syntax ci-database.mjs

~~~text
{"executable":"node","arguments":["--check","infra/dev/ci-database.mjs"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### JS syntax tests/infra.test.mjs

~~~text
{"executable":"node","arguments":["--check","infra/dev/tests/infra.test.mjs"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### Shell syntax initdb/10-app.sh

~~~text
{"executable":"C:/Program Files/Git/usr/bin/sh.exe","arguments":["-n","infra/dev/initdb/10-app.sh"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### Shell syntax healthcheck.sh

~~~text
{"executable":"C:/Program Files/Git/usr/bin/sh.exe","arguments":["-n","infra/dev/healthcheck.sh"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### Shell syntax smoke.sh

~~~text
{"executable":"C:/Program Files/Git/usr/bin/sh.exe","arguments":["-n","infra/dev/smoke.sh"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### Actual Compose config PostgreSQL 18

~~~text
{"executable":"C:/Program Files/Docker/Docker/resources/cli-plugins/docker-compose.exe","arguments":["--project-directory","infra/dev","--env-file","infra/dev/.env.example","--file","infra/dev/compose.pg18.yaml","config","--quiet"]}
exit: 0
stdout:
(empty)
stderr:
WARNING: Error loading config file: open C:\Users\Abu AL-yazeed\.docker\config.json: Access is denied.
~~~

### Actual Compose config PostgreSQL 17

~~~text
{"executable":"C:/Program Files/Docker/Docker/resources/cli-plugins/docker-compose.exe","arguments":["--project-directory","infra/dev","--env-file","infra/dev/.env.example","--file","infra/dev/compose.pg17.yaml","config","--quiet"]}
exit: 0
stdout:
(empty)
stderr:
WARNING: Error loading config file: open C:\Users\Abu AL-yazeed\.docker\config.json: Access is denied.
~~~

### Actual smoke attempt PostgreSQL 18

~~~text
{"executable":"node","arguments":["infra/dev/dev.mjs","smoke","18"]}
exit: 1
stdout:
(empty)
stderr:
FAIL: docker failed (exit 1):
WARNING: Error loading config file: open C:\Users\Abu AL-yazeed\.docker\config.json: Access is denied.
failed to connect to the docker API at npipe:////./pipe/docker_engine; check if the path is correct and if the daemon is running: open //./pipe/docker_engine: The system cannot find the file specified.
~~~

### Actual smoke attempt PostgreSQL 17

~~~text
{"executable":"node","arguments":["infra/dev/dev.mjs","smoke","17"]}
exit: 1
stdout:
(empty)
stderr:
FAIL: docker failed (exit 1):
WARNING: Error loading config file: open C:\Users\Abu AL-yazeed\.docker\config.json: Access is denied.
failed to connect to the docker API at npipe:////./pipe/docker_engine; check if the path is correct and if the daemon is running: open //./pipe/docker_engine: The system cannot find the file specified.
~~~

### Tracked-file whitespace check

~~~text
{"executable":"git","arguments":["diff","--check"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### Tracked-file unchanged check

~~~text
{"executable":"git","arguments":["diff","--exit-code","HEAD"]}
exit: 0
stdout:
(empty)
stderr:
(empty)
~~~

### Actual current branch

~~~text
{"executable":"git","arguments":["branch","--show-current"]}
exit: 0
stdout:
codex/s5-infra-ci-20261013
stderr:
(empty)
~~~

### Actual checkout SHA

~~~text
{"executable":"git","arguments":["rev-parse","HEAD"]}
exit: 0
stdout:
08f9e25e8ada9af56561d815f74b2c7ec9ba7ead
stderr:
(empty)
~~~

## Additional actual tool probes

~~~text
python --version: spawn python ENOENT
py -0p stdout: No installed Pythons found!
psql --version: spawn psql ENOENT
go version: spawn go ENOENT
actionlint -version: spawn actionlint ENOENT
docker compose version: docker: unknown command: docker compose
~~~

The standalone Compose executable was found and successfully used for syntax validation. The default Docker plugin lookup emitted a Docker config access denial, and the local npipe Docker daemon was unreachable. No user Docker credential/config content was read or copied.

## Scope and remaining blockers

Only new files under infra/dev/**, .github/workflows/**, and docs/operations/** were written. No tracked base file, other lane, old Telegram bot, Git branch, HEAD, owner gate, or policy approval was changed. No commit, staging, push, PR, merge, deployment, cloud resource, provider message, private publication, or sensitive product operation occurred.

The main prepare command was not run against the development stack. Unit-test temporary synthetic credentials were removed with their checked, generated test directories; no permanent .env/password file for a development database was left behind. Failed smoke attempts stopped before creating a smoke stack or its credentials.

Runtime exit criteria remain unverified until a local Docker daemon and S0 foundation/Python installation are available. CI syntax/expression validation through actionlint and vulnerability scans also require their missing tools/network dependencies. The operations runbook and S0 contract document the exact commands and integration prerequisites.

Final scope inventory: 18 new files, all under the three S5-owned prefixes. A direct read of every new file found no trailing whitespace; every resolved file path stayed within the workspace. Tracked diff remained empty, branch/HEAD were unchanged, and infra/dev/.local was empty.
