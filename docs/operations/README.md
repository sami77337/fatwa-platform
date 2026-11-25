# S5 development PostgreSQL and CI

**NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD**

This is the issue #6 development infrastructure lane. Gate B remains NOT_PASSED, Gates C/D/E HOLD, Phase01 BLOCKED, and U03/U10 remain pending owner acceptance. This setup contains only a PostgreSQL service. It grants no product permissions and runs no AI, user administration, publishing, messaging, or sensitive worker queues. RabbitMQ is optional in the issue and is deliberately omitted until a separate integration need is accepted.

The checkout at implementation time is codex/s5-infra-ci-20261013, HEAD 08f9e25e8ada9af56561d815f74b2c7ec9ba7ead. It has no Django application or root dependency manifests. See [current publication repair validation](PUBLICATION_REPAIR_20261014.md) and [original recorded validation](VALIDATION_20261013.md) for actual outcomes and [S0 integration contract](S0_INTEGRATION_CONTRACT.md) for the later application handoff. All work from this session remains local.

## Prerequisites

- Node 24.16.0, used only for dependency-free infrastructure tooling and its tests.
- Docker Engine 28 or later, a running local Linux-container daemon, and Compose v2 or later. The CLI also accepts the installed standalone Compose executable through FATWA_COMPOSE_EXE.
- Python 3.13 and S0's committed dependencies are needed only for the later Django checks.
- Access to the official PostgreSQL images when first pulling them. Infrastructure smoke needs no source ZIP, external API key, or project secret.

Docker documents a localhost publishing issue in Engine versions before 28; the CLI refuses those engines. The development port explicitly binds to 127.0.0.1. Smoke stacks publish no host ports. [Docker port publishing documentation](https://docs.docker.com/engine/network/port-publishing/)

Compose and workflow files use the JSON subset of YAML, so Node can parse their syntax without third-party packages. Compose's own validator and actionlint in CI perform the additional engine/workflow checks.

## Windows PowerShell

Use Docker Desktop with Linux containers and its local engine running. Do not change daemon settings, start cloud infrastructure, or install a production service through this runbook. From the repository root:

~~~powershell
node --version
docker --version
docker compose version
node infra/dev/checks.mjs
node --test infra/dev/tests/infra.test.mjs
node infra/dev/dev.mjs preflight
node infra/dev/dev.mjs prepare
node infra/dev/dev.mjs up 18
node infra/dev/dev.mjs ready 18
~~~

If Compose is installed as a standalone executable but its Docker plugin is unavailable, set the path to that local executable in the current PowerShell session:

~~~powershell
$env:FATWA_COMPOSE_EXE = 'C:\Program Files\Docker\Docker\resources\cli-plugins\docker-compose.exe'
node infra/dev/dev.mjs preflight
~~~

The CLI checks the selected Docker endpoint and rejects remote TCP/SSH engines. A Docker config access failure is an environment problem: do not print or copy the user's Docker config, credentials, or login data. The current validation host has a Docker CLI and standalone Compose but no reachable daemon; see the recorded failure.

The prepare command writes only infra/dev/.env and two ignored files beneath infra/dev/.local/. It generates independent local bootstrap/application passwords without displaying them and refuses to overwrite existing or partially prepared credentials. Do not run it to replace credentials for an existing data volume. Protect the .local directory using Windows account ACLs; POSIX permission bits alone do not establish Windows access restrictions. No persistent credential files were created for a development database during this implementation run.

## WSL and Linux

Use Node 24.16.0 and the local Docker Engine/Compose installation, or an enabled Docker Desktop WSL integration. Run inside the Linux checkout from its repository root:

~~~sh
node infra/dev/checks.mjs
node --test infra/dev/tests/infra.test.mjs
node infra/dev/dev.mjs preflight
node infra/dev/dev.mjs prepare
node infra/dev/dev.mjs up 18
node infra/dev/dev.mjs ready 18
~~~

On Linux, the enclosing .local directory is mode 0700. Password files are mode 0644 so PostgreSQL's container UID can read Compose's mounted file secrets; the host directory prevents other unprivileged host users from traversing to them. Docker administrators can access container data and are part of the local trust boundary. File secrets remain outside version control and are mounted read-only.

Shell scripts are written with LF line endings. If a later Windows checkout applies CRLF conversion, the infrastructure validator rejects them before startup; restore these three scripts to LF.

## Connections, readiness, and storage

The default connection is 127.0.0.1:55432, database fatwa_reference, role fatwa_app. The ignored application password file is the local credential source. Supply it to S0's accepted environment interface after integration; never use fatwa_bootstrap as an application login or publish a connection URL containing credentials.

Change only FATWA_DEV_PORT in infra/dev/.env if the default host port is occupied. The CLI permits unprivileged ports and overrides an inherited FATWA_DEV_PORT with the validated file value. Both majors use that same host port, so stop one before starting the other.

The readiness check authenticates over TCP as fatwa_app, confirms the expected role, and verifies NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, and NOBYPASSRLS. It does not treat the entrypoint's temporary Unix-socket bootstrap server as application readiness. Initialization gives that role ownership of only its development database/schema; it does not bind any historical product permission row.

| Major | Image tag | Compose project | Named data volume | Container data mount |
| --- | --- | --- | --- | --- |
| 18 primary | postgres:18.6-bookworm | fatwa-s5-dev-pg18 | fatwa-s5-dev-pg18_pgdata18 | /var/lib/postgresql |
| 17 fallback | postgres:17.11-bookworm | fatwa-s5-dev-pg17 | fatwa-s5-dev-pg17_pgdata17 | /var/lib/postgresql/data |

The image tags are exact minor releases verified against the official image listing; they are not immutable digest locks. An actual smoke run prints the pulled image identity and server version. No image digest or PostgreSQL runtime result is asserted in the local evidence.

PostgreSQL 18 changed the official image data layout. The two definitions therefore use different mount targets and separate volumes. Never reuse one major's data volume with the other image. [Official PostgreSQL image storage and initialization documentation](https://hub.docker.com/_/postgres)

## PostgreSQL 17 fallback and clean stop

The fallback starts its own empty development database; it does not convert or migrate an 18 cluster.

~~~sh
node infra/dev/dev.mjs down 18
node infra/dev/dev.mjs up 17
node infra/dev/dev.mjs ready 17
node infra/dev/dev.mjs down 17
~~~

The down command stops/removes only the selected development project's containers and network. It keeps persistent data volumes and ignored credential files. There is no general reset, volume-delete, global prune, or recursive user-directory cleanup command. If disposal of a retained development volume is later required, inspect its exact project/name and obtain specific authorization for that data removal outside this task.

## Synthetic backup/restore and persistence smoke

~~~sh
node infra/dev/dev.mjs smoke 18
node infra/dev/dev.mjs smoke 17
~~~

Each smoke run creates a new generated project with a random suffix and its own named volume and temporary credentials. It publishes no host ports and mounts only the three infrastructure scripts. It never connects to fatwa-s5-dev-pg18, fatwa-s5-dev-pg17, or a supplied production/requester database.

Fixture identity is s5-synthetic-v1: two deliberately artificial rows defined in infra/dev/smoke.sh, including an Arabic title that is not a source-book excerpt. The command prints Git HEAD, the fixture script SHA256, actual image identity, and PostgreSQL server version. It then:

1. Waits for authenticated restricted-role readiness.
2. Inserts exactly two synthetic rows.
3. Verifies the app role cannot create roles/databases or read password hashes.
4. Dumps the synthetic database using pg_dump's custom format.
5. Restores into a second database inside the same isolated smoke stack.
6. Compares row counts and deterministic content hashes.
7. Recreates the container and repeats the content checks against the persisted volume.
8. Removes only the generated smoke project's containers/network/volume and its direct temporary files.

Cleanup runs on verification failure as well. If cleanup itself fails, the command reports both the original failure and the generated project identifier and retains the temporary files for diagnosis. It never runs Docker volume/system prune.

The provided backup path is this isolated synthetic smoke. It is not a general backup/restore command for arbitrary databases or owner data. Successful Node tests of the command planning do not establish successful PostgreSQL execution.

## CI behavior

[The S5 workflow](../../.github/workflows/s5-ci.yml) uses read-only repository permissions, SHA-pinned official actions, no persisted checkout credential, path filters, finite timeouts, and no deployment jobs.

Before S0 integration, CI runs infrastructure boundary/regression tests, JavaScript and POSIX shell syntax, actual Compose syntax, actionlint, a Python 3.13 vulnerability audit of S5's pinned CI tools, and real synthetic smoke on PostgreSQL 18 and 17. The application detector writes an explicit NOT_RUN notice for application lint, format, types, Django system/migration checks, PostgreSQL tests, and application dependency auditing. These are not reported as project passes.

When S0 is present, a missing/invalid/uncommitted integration contract fails the infra job. Once the committed contract is available, the separate application matrix installs S0 dependencies, verifies the actual PostgreSQL backend and test role, and runs the declared checks. Its temporary CI role has CREATEDB only to create Django test databases; the development application role remains NOCREATEDB. CI passwords are explicitly disposable public synthetic fixture values tied to a run identifier, never repository/project/production credentials. Vulnerability audits use public advisories without an API key.

Writing this workflow locally did not execute GitHub Actions. Runtime CI, vulnerability-audit, and actionlint outcomes remain NOT_RUN on the current host.

## Current handoff limits

The current host lacks a running Docker daemon, Python 3.13, psql, Go/actionlint, Django, and S0's committed installation/testing interface. Bundled Python 3.12.14 was found for the controller security tests; it does not establish Django/Python 3.13 acceptance. Unit and syntax outcomes are documented separately from those missing runtime checks. Original source ZIPs were not supplied to this lane. No import counts, catalog acceptance, coverage, application performance, or owner approval are claimed.
