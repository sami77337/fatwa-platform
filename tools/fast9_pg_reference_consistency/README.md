# Guarded PostgreSQL opt-in

Default offline command (does not connect to a database):

```text
python -B -m unittest discover -s tests/fast9_pg_reference_consistency -t . -v
```

Actual PostgreSQL is **NOT_RUN** until an operator supplies a separately
preauthorized disposable Wave7 synthetic environment. This lane does not locate,
initialize, migrate, reset or inspect any owner/development database. Do not use
`manage.py test` with default settings or `--keepdb` for these tests.

The existing trusted `tests.wave7_foundation.runner.Wave7TestRunner` must own the
lifecycle. Its base must already be a provisioned, owned synthetic database with
the existing Wave7 prerequisites installed. The test database must not exist.
The runner checks the actual base name, role, PostgreSQL 17/18 and immutable
ownership/OID, rejects a pre-existing test database, creates only its exact test
database, verifies identity before initializing it, runs existing migrations,
and cleans up only the test database it created. No new migrations or schema
definitions are added by this lane. The lane guard performs read-only ownership
verification before invoking that runner, and repeats it on the exact test
database before fixture insertion. Both Django settings and any cached connection
must match the explicit target, port and synthetic credential before that query.

Only in that preauthorized synthetic process, supply these explicit values:

| Variable | Required value |
| --- | --- |
| `FAST9_PG_ACK` | `FAST9_DISPOSABLE_SYNTHETIC_ONLY` |
| `FATWA_PRODUCTION` | `0` |
| `FATWA_WAVE7_SYNTHETIC_WRITES` | `1` |
| `DJANGO_SETTINGS_MODULE` | `config.settings.wave7_test` |
| `PGHOST` | `127.0.0.1` |
| `PGPORT` | Explicit isolated port 1024–65535, excluding 5432/55432/8000 |
| `PGUSER` | `wave7_synthetic` |
| `PGDATABASE` | `wave7_synthetic_fast9_reference` |
| `PGTESTDATABASE` | `test_wave7_synthetic_fast9_reference` |
| `PGPASSWORD` | Explicit credential for that disposable synthetic role only |

Connection/service overrides (`DATABASE_URL`, `PGSERVICE`, `PGSERVICEFILE`,
`PGHOSTADDR`, `PGPASSFILE`, `PGOPTIONS`) must be absent. Credentials are neither
discovered nor logged; no sample real credentials are provided.

Run from repository root:

```text
python -B -m tools.fast9_pg_reference_consistency --postgresql
```

Exit 2 / `NOT_RUN` means configuration or owned-target prerequisite unavailable.
Exit 1 / `FAIL` or `ERROR` means the guarded run failed; it must not be reported
as acceptance. Exit 0 / `PASS` concerns fabricated synthetic tests only.
The suite deliberately lives in `postgresql.py`, outside `test_*.py` discovery.
No skip/xfail fallback or SQLite surrogate exists.

Current actual result: exit 2 / `NOT_RUN` /
`EXPLICIT_SYNTHETIC_CONFIGURATION_REQUIRED`. Seven PostgreSQL tests collected
offline, zero executed. Full validation and fixture hashes are in
[the adapter README](../../apps/fast9_pg_reference_consistency/README.md).
