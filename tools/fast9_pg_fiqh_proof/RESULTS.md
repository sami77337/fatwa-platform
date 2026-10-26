# FAST9 pg-fiqh-proof execution record

Date: 2026-10-27. Base: `0769f66e93fdf710ca55e9e68e87430a93f14c40`.
Branch: `codex/20261027-fast9-pg-fiqh-proof-pc1`.
Target: `codex/20261026-fast8-integration-pc1` (not main).
Tests below ran against the lane working tree based on this SHA; the final
commit SHA and remote CI status belong in the draft PR handoff. No claim that
the unchanged base alone contains these new tests is intended.

Environment observed: Python 3.13.15, Django 5.2.18, psycopg 3.3.6, Windows.

| Command | Actual result |
| --- | --- |
| `python -B -m unittest tests.fast9_pg_fiqh_proof.test_offline -v` | 11 tests, PASS, zero skips; includes refused connection sentinel |
| Explicit combined Django command in README | 43 tests, PASS: 11 new + 32 affected FAST8 tests; zero skipped test cases; Django reports unused database setup omitted |
| `python -m ruff check --no-cache tests/fast9_pg_fiqh_proof tools/fast9_pg_fiqh_proof` | PASS |
| `python -m ruff format --check tests/fast9_pg_fiqh_proof tools/fast9_pg_fiqh_proof` | PASS |
| `python -B tools/dev/qa.py system` | PASS, zero system-check issues; unreachable database configuration, no DB work |
| `git diff --check` | PASS |
| New explicit PostgreSQL module | **NOT_RUN**, 8 cases discovered offline only |
| Browser | **NOT_RUN**, outside this service acceptance lane |

The complete combined command was:

```text
python -B manage.py test tests.fast9_pg_fiqh_proof.test_offline tests.fast8_fiqh_navigation.test_cli tests.fast8_fiqh_navigation.test_django_adapter tests.fast8_fiqh_navigation.test_preflight tests.fast8_fiqh_navigation.test_services --settings=config.settings.test --noinput --verbosity=2
```

## Failures and limitations actually observed

- `docker version --format '{{.Server.Version}}'` could not connect to
  `dockerDesktopLinuxEngine`: named pipe unavailable. No disposable local
  PostgreSQL prerequisite was available; no PostgreSQL connection, fixture
  write, migration, or PostgreSQL test was attempted locally.
- Initial offline test run before implementation was red (missing runner/proof
  modules and unmet guard/discovery assertions). After implementation the final
  11-case suite passed. Initial format check reported four unformatted files;
  formatting was applied within the two owned folders and the check then passed.
- Two initial read-only inspection paths (`config/settings/ci.py` and a
  `backend*` workflow glob) did not exist. Inspection continued with the actual
  `config/settings/test.py` and `.github/workflows/b6-integration.yml` files.
- No broad database-dependent discovery was run against a default database.
  B6/C6/D6 inherited CI is checked on the exact remote head separately; the
  shared workflow files do not collect either new FAST9 module. A green
  inherited check therefore proves neither this suite's PostgreSQL execution
  nor source-owner acceptance. Coordinator registration on both disposable
  PG17/18 jobs remains required.

Fixture ID and hashes are pinned in README and `proof.py`. No owner archive was
read or copied. Existing source files, Arabic bytes, timestamps, and CRLF files
were not edited. Only fabricated catalog records may be created by the guarded
runner when subsequently registered in B6.

## Independent review

One runtime-supported `gpt-6-astra` reviewer was started for read-only final
review, with no write permission requested and no database execution. Its
independent offline run passed all 11 tests; Ruff check/format also passed.
Final review: **PASS for static/offline review**, no blocking findings. The
reviewer verified the Django 5.2.18 lifecycle and collision refusal. The sole
documentation follow-up was the then-missing `RESULTS.md`, supplied by this file.
Review does not substitute for PostgreSQL execution (**NOT_RUN**).

Official state remains: Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.
Source-owner/catalog/policy/production acceptance remains NOT_CONNECTED.
