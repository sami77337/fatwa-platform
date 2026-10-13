# S0 public reference development foundation

**NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD.** Gate B NOT_PASSED;
C/D/E HOLD; Phase01 BLOCKED. U03/U10 remain OWNER_APPROVAL_PENDING.

This implements catalog metadata persistence and public reads on Django 5.2 /
Python 3.13 / PostgreSQL 18 preferred, 17 fallback. It does not prove runtime
acceptance: see [S0_RESULT.md](S0_RESULT.md) for actual execution evidence.

## What is implemented on disk

- Settings split into development/test/production. DEBUG defaults false, local
  hosts are explicit, signing keys come from the environment or an ephemeral
  development value, and production boot fails closed.
- ReferenceWork -> ReferenceEdition -> ReferenceHeading with original source
  IDs, title, ordering, parent edges, printed part/page, page ID, edition lineage
  hashes and an ingest checksum. Source titles are never replaced by normalized
  search text. A string part supports introductions as well as numbered parts.
- Two PostgreSQL migrations: schema/uniqueness and immutable hierarchy guards.
  PostgreSQL checks/triggers reject orphan/cross-edition/wrong-depth edges and
  UPDATE/DELETE mutations; strict parent depth prevents cycles. The adapter
  inserts one complete snapshot atomically with parents before children.
- Typed S1 persistence interface, dry-run by default, checksum-pinned commit,
  unchanged reruns, and conflict rejection. No source parsing/import CLI is
  duplicated. See [INGEST_CONTRACT.md](INGEST_CONTRACT.md).
- Bounded GET/HEAD APIs and Arabic SSR templates with native details/summary,
  lazy htmx child loading, breadcrumbs, edition attribution, original-title
  exact search and normalized/literal token search. See [API.md](API.md).
- Scoped synthetic tests and a read-only measurement command. No latency,
  coverage, browser accessibility or PostgreSQL success is claimed yet.

No auth/admin/session apps, personal cases, permissions, workflow transitions,
AI integrations, scholarly answers, approvals, publication, delivery, exports
or production operations are implemented. Book 622 is one Hanbali work's index,
not a global fatwa taxonomy or published-ruling corpus.

## Development setup for the coordinator/S5

Use a disposable Python **3.13** virtual environment selected by S5; do not
commit environments, caches or generated artifacts. Runtime and transitive
requirements are exactly pinned; a clean installation has **NOT_RUN** here.

~~~powershell
python --version
python -m pip install --no-deps -r requirements-dev.txt
python -m pip check
~~~

S5 must supply an isolated PostgreSQL 18 or 17 development database and a
separate disposable test database. Never point these commands at production.
Provide PGHOST, PGPORT, PGDATABASE, PGUSER and PGPASSWORD through the environment;
PGTESTDATABASE defaults to test_fatwa_reference_dev. No credentials are in code.
Django's test runner needs permission to create/drop its disposable test DB;
the catalog-serving process should use a separate SELECT-only role supplied by
S5. S0 neither creates roles nor issues grants.

~~~powershell
python manage.py check --settings=config.settings.test --database=default
python manage.py makemigrations --check --dry-run --settings=config.settings.test
python manage.py migrate --settings=config.settings.development
python manage.py test tests/reference --settings=config.settings.test --verbosity=2
python manage.py runserver 127.0.0.1:8000 --noreload
~~~

Open http://127.0.0.1:8000/fiqh. An empty migrated database shows an honest empty
catalog. Populate through the reviewed S1 adapter integration; no real source
rows are seeded by S0. Templates load htmx from the pinned django-htmx package,
served locally through the restricted public asset view, with no CDN requests.
The same fixed asset view works with DEBUG false. Links/forms also work without
JavaScript; native summary controls support keyboard expansion.

FATWA_PRODUCTION=1 or config.settings.production refuses startup. Sensitive
operations cannot be enabled by flipping a flag. Liveness at /healthz is
separate from schema/database reachability at /readyz; neither is a gate pass.

## Verification commands

~~~powershell
python -m unittest discover -s tests/reference -p test_records.py -v
python -m ruff check --no-cache config apps/reference tests/reference manage.py
python -m ruff format --check --no-cache config apps/reference tests/reference manage.py
python -m mypy --cache-dir=tests/reference/.mypy_cache
python -m coverage run manage.py test tests/reference --settings=config.settings.test
python -m coverage report
node --check apps/reference/static/reference/tree.js
~~~

The type check currently covers the strict Python-only record, query-validation
and normalization contracts. Full ORM/view typing, dependency audit and CI
execution require S5 integration and appropriate tooling. Coverage output is
configured within tests/reference; it is not acceptance evidence until run.

After S1 validates and imports the full original metadata, measure the actual
edition (substitute its database ID), retaining command output with source SHAs:

~~~powershell
python manage.py benchmark_reference --edition 1 --expected-headings 11397 --query "كتاب" --repeats 5
~~~

The command performs reads only, requires real PostgreSQL 17/18 and the expected
actual row count, and emits actual ORM query counts plus measured latencies,
PostgreSQL version, input identity and source hashes. It excludes HTTP rendering.
B-tree indexes cover stable child enumeration, source identity/order and exact
titles. Normalized substring search is a bounded scan with parameter binding
and a 3-second DB statement timeout; pg_trgm is deferred until independently
measured. No query plan/latency for 11,397 rows has been asserted.

## Acceptance and integration still required

Review and run the migrations, including consistency/reversal checks, against
real PostgreSQL. Apply S1 parser/validator and confirm all original IDs/titles,
11,397 headings / 32 roots / depth 5 and printed page references before calling
source acceptance complete. Source hashes are verified locally; full validation
and ORM import are NOT_RUN. S2 must test desktop/mobile keyboard and screen-reader
flows, including htmx/error/retry and no-JS behavior. S4 must run independent
negative HTTP/security QA. S5 owns Compose, CI and dependency audit. The root
README is outside S0 ownership; the coordinator must add a link to this guide.

Pins were checked against official package metadata, including
[Django 5.2.18](https://pypi.org/project/Django/5.2.18/),
[psycopg 3.3.6](https://pypi.org/project/psycopg/3.3.6/) and
[django-htmx 1.29.0](https://pypi.org/project/django-htmx/1.29.0/).
The [Django constraint reference](https://docs.djangoproject.com/en/5.2/ref/models/constraints/)
and [htmx template tags](https://django-htmx.readthedocs.io/en/latest/template_tags.html)
are the upstream API references. Package installation was not possible here.
