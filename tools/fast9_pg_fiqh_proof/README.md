# FAST9 synthetic PostgreSQL source-trail proof

Base: `0769f66e93fdf710ca55e9e68e87430a93f14c40` (FAST8 draft #151).
Only `tests/fast9_pg_fiqh_proof/` and `tools/fast9_pg_fiqh_proof/` are changed.
No shared settings, URLs, migrations, source files, or CI are modified.

The suite joins the real `ingest_catalog` -> PostgreSQL ->
`DjangoNavigationReader` -> `CatalogNavigation` services. It does not replace
the reader with a mock. Eight PostgreSQL cases verify all nine original rows,
source IDs, edges, sibling positions, order, five depths, two roots, Arabic
UTF-8 (including whitespace and combining marks), printed part/page, edition
metadata, source pins, and unchanged persisted fields including timestamps.
Additional probes check stale and coherently recomputed checksums, missing rows,
foreign parents, unknown editions, disconnected readers, and nested transactions.
Three attempted DML verbs must return actual PostgreSQL SQLSTATE `25006`.
A second synthetic connection commits a change while the reader snapshot remains
stable; a later read must reject the changed catalog.

## Exact fixture

Reuses **only** the fabricated `tools.fiqh_reading_trail.fixtures` contract:

- ID: `fast7c-reading-trail-synthetic-v1`
- Canonical UTF-8 fixture SHA256:
  `b1abc9c56a6173f8c7c2f573af746aaee6140aaea58df26b6ffebd7803e12d98`
- Catalog checksum:
  `5349fd891831a0e2d0d831aede0a3353c5dff8bdf931c70e8645856f93c04c45`
- Rows in source order: `1, 2, 40, 41, 42, 3, 8, 9, 10`.
- Archive/input pins `a*64` and `b*64` are fabricated assertions, **not** hashes
  of owner archives. Book ID `622` does not imply source-owner acceptance.

Literal pins are checked before discovery/creation and every fixture ingest.
They are never recalculated and silently accepted as a new expected value.

## Offline checks (no database)

Use the repository's pinned dependencies and Python 3.13:

```powershell
python -B -m unittest tests.fast9_pg_fiqh_proof.test_offline -v
python -B manage.py test tests.fast9_pg_fiqh_proof.test_offline tests.fast8_fiqh_navigation.test_cli tests.fast8_fiqh_navigation.test_django_adapter tests.fast8_fiqh_navigation.test_preflight tests.fast8_fiqh_navigation.test_services --settings=config.settings.test --noinput --verbosity=2
python -m ruff check --no-cache tests/fast9_pg_fiqh_proof tools/fast9_pg_fiqh_proof
python -m ruff format --check tests/fast9_pg_fiqh_proof tools/fast9_pg_fiqh_proof
```

The offline subprocesses raise if Django attempts a database connection. Mock
cursors are used only to test refusal/creation-race control flow; these results
are never PostgreSQL evidence. No skip or xfail is used.

## Coordinator opt-in: disposable B6 PG17 and PG18 only

The coordinator must add the following explicit-module command to **both**
versions of B6's `postgresql` job, using its already preauthorized disposable
service. Run serially, without another process creating the same test name.
The service credentials remain the existing B6 synthetic CI credentials; this
lane neither reads credentials from files nor supplies production credentials.
Do not run this on an existing user/development database or manually migrate it.

```yaml
- name: FAST9 real synthetic source-trail acceptance
  env:
    FAST9_PG_FIQH_SYNTHETIC_ONLY: '1'
    FATWA_PRODUCTION: '0'
    DJANGO_SETTINGS_MODULE: config.settings.test
    PGHOST: 127.0.0.1
    PGPORT: '5432'
    PGUSER: fatwa_ci
    PGDATABASE: b6_ephemeral
    PGTESTDATABASE: test_fast8_fiqh_navigation_synthetic
    EXPECTED_PG_MAJOR: ${{ matrix.postgres }}
  shell: bash
  run: |
    set -o pipefail
    python -B manage.py test tests.fast9_pg_fiqh_proof.postgresql \
      --testrunner=tools.fast9_pg_fiqh_proof.runner.SyntheticRunner \
      --settings=config.settings.test --noinput --verbosity=2 \
      2>&1 | tee fast9-pg-fiqh-proof.log
```

The runner refuses missing opt-in, wrong settings/database/host/port/role/version,
keepdb, parallel runs, filtered/partial collections, and any label other than the
exact module. The existing name `test_fast8_fiqh_navigation_synthetic` is retained.
Direct discovery without this runner raises **before** database setup. The
original FAST8 pre-discovery guard and suite are untouched.

Before creation, read-only queries verify live `b6_ephemeral` identity and check
that the exact test database is unused. The maintenance connection is verified
as `postgres` on the same role/version; its usual fallback is rejected. The
creation path never drops or reuses an occupied name, even if a create race occurs.
The newly created database identity is checked before Django's existing migrations,
then again before every fixture write and before teardown. Only the successfully
created test database is dropped after the run. A setup failure is a failure;
there is no automatic retry or destructive cleanup of a suspect database.

Capture the complete log as a CI artifact. `FAST9_PROOF` JSON lines report actual
Git SHA/dirty state, literal fixture pins, live database/role/server version,
transaction modes, DML SQLSTATE, snapshot evidence, and test counts. A result of
`PASS_SYNTHETIC_ONLY` applies only to this fixture; nonzero exit (including teardown)
must fail CI. Missing service/opt-in is an error, never a pass or skip.

## Execution evidence and limits

Local PostgreSQL: **NOT_RUN**. Docker's Linux engine pipe is unavailable and no
preauthorized disposable PostgreSQL service was supplied. No local database was
contacted or created. PostgreSQL acceptance remains pending coordinator B6
registration. Inherited B6/C6/D6 green does **not** cover this new module.

Local offline and review results are recorded in `RESULTS.md` alongside this file.
No browser claim is made: this lane tests the source-trail service boundary.

Source-owner/catalog acceptance: **NOT_CONNECTED**. Policy and production
acceptance: **NOT_CONNECTED**. Gate B **NOT_PASSED**; C/D/E **HOLD**;
Phase01 **BLOCKED**; **SCOPE_DEVIATION_HOLD**; **NOT_DEPLOYED**;
U03/U10 **OWNER_APPROVAL_PENDING**. No scholarly approval, publishing, private
records, or new public write endpoints are enabled.
