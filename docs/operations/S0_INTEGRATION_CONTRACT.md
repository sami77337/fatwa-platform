# S0 integration contract for S5 CI

**NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD**

S5 owns infrastructure, workflows, and these operations notes. S0 owns manage.py, settings, application dependencies, models/migrations, templates, and its tests. No S0 file was created or changed here. The coordination runbook permits S5 to use S0's declared installation commands after those commands have been committed.

## Current state

There is no manage.py and no active application contract in this checkout. application.mjs detect therefore emits NOT_RUN. application-contract.example.json is an inactive shape/example with placeholder paths; its status deliberately fails activation.

The coordinator must supply infra/dev/application-contract.json during the later integration, using the actual reviewed S0 settings module, dependency files, and commands. This is an S5-owned file. The current session did not create an active contract, use another lane's worktree, cherry-pick anything, or perform any Git publishing action.

## Required fields

| Field | Contract |
| --- | --- |
| version | Exactly 1 |
| status | Exactly S0_COMMITTED_COMMANDS_CONFIRMED after the commands are recorded in the integrated commit |
| settings_module | Actual dotted S0 settings module that keeps sensitive operations disabled |
| dependency_files | Nonempty list of relative dependency/lock manifest paths that S0 owns |
| database_env | Map of actual S0 variable names to url, host, port, name, user, or password |
| commands | Nonempty argument-array lists for every required stage |

The runner compares manage.py, the active contract, and every declared dependency file with their contents at checked-out HEAD. Merely creating an uncommitted contract or placeholder manifest does not unlock application CI. Repository-relative paths cannot traverse outside the repository. Commands run as argument arrays through the selected Python runtime, with shell parsing disabled.

Required stages:

| Stage | Allowed form and required behavior |
| --- | --- |
| install | python -m pip install using a declared requirements file, or the committed project root |
| lint | python -m ruff check with S0's actual targets/options |
| format | python -m ruff format --check with S0's targets/options |
| type | python -m mypy with S0's targets/configuration |
| system | python manage.py check |
| migration | python manage.py makemigrations --check --dry-run |
| tests | python manage.py test or python -m pytest with S0's actual PostgreSQL test targets |

The example's target names are placeholders, not declarations of existing S0 files. If S0 requires another tool/interface, adapt the S5 runner and regression tests as an explicit reviewed integration change. Do not silently guess or skip a required stage. S0 must also provide its own typed/test dependencies such as plugins or Django stubs where needed.

## Database environment

The CI job owns an ephemeral service and supplies these base fields:

~~~text
PGHOST=127.0.0.1
PGPORT=5432
PGDATABASE=fatwa_ci
PGUSER=fatwa_ci
PGPASSWORD=<disposable synthetic CI fixture value>
~~~

The contract maps these values to the actual accepted S0 settings interface. For example, database_env may map DATABASE_URL to url if that is S0's declared interface. The runner creates the URL in process memory without logging it. It also sets DJANGO_SETTINGS_MODULE from the committed contract.

Before running application checks/tests, the runner uses Django's actual connection and requires:

- The default engine is django.db.backends.postgresql.
- The connected database and role are both fatwa_ci.
- The role has no superuser, role-creation, replication, or row-security-bypass capability.
- CREATEDB is present solely to allow Django's temporary test-database creation in this disposable service.
- The actual PostgreSQL server version is printed.

The local development role fatwa_app has NOCREATEDB. Its migration permission covers only its owned synthetic development database/schema. These database-level setup permissions do not approve any historical product permission or enable privileged business endpoints.

The matrix contains 18.6-bookworm and the separate 17.11-bookworm fallback. No SQLite fallback can satisfy the application probe. The PostgreSQL service bootstrap role is used only to provision the temporary CI role/database, never as S0's application identity.

## Dependency/security checks and evidence

infra/dev/requirements-ci.txt pins S5's lint/type/audit tools. CI installs and audits that tooling even before S0 exists. After S0 installation, a separate audit inspects the application's installed Python dependency environment and fails on reported vulnerabilities or scan errors. Neither scan needs an external API key or project secret; package/advisory downloads require network access.

The pipeline contains separate names for infra checks, synthetic database smoke, and S0 application checks. A green infra unit test is not evidence that PostgreSQL ran. A skipped application job is not an application pass. The detector records the NOT_RUN application list in stdout and the GitHub step summary.

A later accepted run must preserve the checkout SHA, exact contract, PostgreSQL image/server identities, literal commands/results, and fixture identity. Original owner ZIPs require their own supplied-file identities; the s5-synthetic-v1 smoke fixture does not establish source import completeness.

## Handoff sequence

1. Independently review the committed S0 foundation and its declared install/check/test interface in the authorized integration checkout.
2. Fill the S5 active contract using that interface; include all required stages and the real database environment mapping.
3. Run the contract regression checks, infrastructure checks, and real synthetic smoke for both majors on a working local daemon.
4. Run the conditional application matrix with Python 3.13 and record actual PostgreSQL test/check/audit results.
5. Keep deployment, merges, pending policy acceptance, and sensitive operations outside this development work.

The local record currently lists PostgreSQL execution, Python/Django checks, actionlint, and dependency audits as NOT_RUN for their actual missing dependencies. Gates and owner approvals remain unchanged.
