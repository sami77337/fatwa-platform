# E5 foundation execution evidence

Selected existing Cloud executor remained usable; no new task/thread, owner
workstation or alternate host was used. Environment ID:
`ccarenv_b64_Y2NhcmVudl8yZWFiZmI1OTRmYzA4MTkxOWI1YTczZDhkOTg2ZTMwMg`.
Task URL/ID: NONE newly exposed. Parent source thread:
`01a1173c-6c30-723a-828d-8948d842003d`. Shell, Git and Docker calls actually ran.
Runtime: Python 3.13.5 via explicit `/usr/bin/python3.13` uv venv, Node 24.19.0,
uv 0.12.23, Docker 28.4.0, Debian 13.6 Linux. Usage/quota NOT_OBSERVED.

Original `/workspace/fatwa-platform` remained on Wave6
`79149964da658c3f9192ab1c1512016ccf950aa4`, clean. New worktree:
`/workspace/fatwa-wave7-e5-foundation`, branch `codex/20261017-wave7-e5-foundation`,
created only after confirming absence, from exact accepted
`8a362b0ff69dadbac288d05a7cf33d5fdd36951e`. No main/integration merge performed.

## Real commands and results before the first publication

```text
uv --cache-dir /tmp/fatwa-e5-uv-cache venv --python /usr/bin/python3.13 .venv
uv --cache-dir /tmp/fatwa-e5-uv-cache pip install --python .venv/bin/python --index-url https://pypi.org/simple --no-deps -r requirements.txt
.venv/bin/python tools/dev/qa.py system
.venv/bin/python -B -m unittest tests.wave7_foundation.test_contracts tests.wave7_foundation.test_guard_config -v
```

Existing eight exact pins only; no root dependency edits. Initial accepted-base
system check passed, zero issues. Initial pure contracts RED was an actual
missing-app ImportError; after implementation, 10 contract methods passed.
Guard configuration RED was an actual absent-module error, then six methods
passed; two later default-registration/missing-flag methods bring pure total to
**18 methods (10+8), 0 failures/errors/skips**. Additional positive coverage is
retained evidence, not a claimed preexisting bug fix.

Actual PG18 early schema run (before SQL guards/fixture seed): **17 methods,
8 assertion/subtest failures + 1 error**. Unguarded DML, mutation/deletion of
originals/events and fabricated snapshots succeeded incorrectly. Missing seed
helper caused the error. Actual native uniqueness/hash/rollback/race/unknown-DB
checks already passed and remain retained evidence. Adding migration 0002 and
the guarded fixture made all 17 pass; four added source/readiness/unknown-migrate
checks yield the final **21 database methods**, no failures/errors/skips on the
verified full runs. Counts of failure events are not independent failing methods.

Two initially generated makemigrations commands used the separate Wave7 settings
with default unreachable port 1: migration history read was unavailable and
Django emitted a warning, but generated the new files. No migration/write ran on
that target. Subsequent real isolated checks on both actual PG versions verified
migration history, no model drift and actual application.

The Cloud-local test resource helper (temporary, not a product runner):

```text
.venv/bin/python /tmp/wave7-e5-control.py start 17
.venv/bin/python /tmp/wave7-e5-control.py start 18
.venv/bin/python /tmp/wave7-e5-control.py run 17 <command below>
.venv/bin/python /tmp/wave7-e5-control.py run 18 <command below>
```

Each is an independent new Cloud Docker container, random loopback-only published
port and unique `wave7_synthetic_e5_pg<major>_<uuid>` name. User is the fixed
`wave7_synthetic`, test DB exactly `test_` + base. Password is disposable synthetic
fixture configuration. PG17/18 official bookworm image data mounts are tmpfs,
covering the correct image-specific volume. No owner catalog, sibling service,
source archive/data, public port, real credential or security configuration used.
The helper sanitizes inherited PG/Django/Fatwa/credential variables with existing
qa.environment(), then supplies only its own recorded test configuration. Cleanup
removes only its exact recorded containers; no prune or broad removal.

Run with each service's explicit synthetic environment:

```text
.venv/bin/python -c "import django;django.setup();from apps.intake_workflow.guards import initialize_synthetic_database;print(initialize_synthetic_database(synthetic_fixtures_only=True))"
.venv/bin/python manage.py check --database default --settings=config.settings.wave7_test
.venv/bin/python manage.py makemigrations --check --dry-run --settings=config.settings.wave7_test
.venv/bin/python manage.py migrate --noinput --settings=config.settings.wave7_test
.venv/bin/python manage.py migrate --check --settings=config.settings.wave7_test
.venv/bin/python manage.py showmigrations intake_workflow --settings=config.settings.wave7_test
.venv/bin/python manage.py test tests.wave7_foundation.test_database --noinput --settings=config.settings.wave7_test --verbosity=2
```

Both migrations discover/apply successfully. Real guards reject unknown occupied,
empty unclaimed and foreign-marker databases without reset or write. An actual
migrate subprocess against a task-created unknown fixture leaves its existing
row unchanged and creates no django_migrations table. Known owned nonempty data
survives initializer reuse and accepts another batch. Atomic rollback leaves no
batch/item/ref/event; a real two-connection unique-key race has one winner and
one rejected insert with no partial child. This is foundation storage evidence;
E1/E2 CLI/service idempotency/review acceptance remains NOT_RUN.

Actual unsafe HTTP POST/PUT/PATCH/DELETE tests returned 405 with **zero queries**
under enabled synthetic settings. Git diff verified public/base/development/test/
production settings, config middleware/URLs and requirements unchanged. Default
public app registration remains off; no auth/sessions/admin introduced.

CI registers actual pure labels once each in C6 Windows/Linux and the DB module
only in a new disposable B6 PG17/18 job. Head SHA, actual PG version/role/database
and verbose case log are uploaded. No dependent-lane test label is guessed.
Windows and fresh committed-head CI results belong to the PR/final handoff;
before actual execution they are NOT_RUN, not inferred from Linux tests.

Raw local logs stay private under `/tmp/fatwa-wave7-e5-evidence/`. The PR/final
handoff records exact committed head, path list, run links and current limitations.
No independent review, full Wave7 acceptance, source/product acceptance, browser
execution, deployment or later wave is claimed.
`NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED`.
