# PR58 independent review correction — partial, numeric decision blocked

**Historical three-fix increment at 47b040105c1a122171af2bdaa1d05ad78672141f.**
The later leadership-approved numeric correction supersedes the pending-decision
status below; see [LOSSLESS_STORAGE.md](LOSSLESS_STORAGE.md). Earlier RED/CI
counts remain evidence for their own heads, not the new candidate.

Review input head: `8eebb1c97f79f2eb5cbe4f4930a493e0c8ed1241`.
Same branch/PR58, development base `8a362b0ff69dadbac288d05a7cf33d5fdd36951e`.
No replacement branch/PR or dependent-lane implementation. No freeze/acceptance claim.

## Actual RED evidence and corrected behavior

The first new regression run reproduced all four review findings on each actual
PG17.11/PG18.6 service: **25 discovered methods, 30 failing subtests + 1 error**.
Those 25 consisted of the original 21 methods accidentally also discovered via
an imported TestCase class plus four new review methods. The import was changed
to a module alias, so explicit discovery no longer duplicates that original class.
The 30 failure events were three ownership cases, 12 duplicate-key cases and 15
invalid-ID cases; the numeric source mismatch was the error. The public range
type control already rejected, while standalone enum/domain did not. These are
failure events/subtests, not 30 independent methods. The pure numeric probe also
failed: **19 methods, 1 failure**, with `73.0 != Decimal('73.000000000000001')`.

1. Ownership inventory now excludes only actual PostgreSQL system/temporary
   namespace names, never the wildcard `pg_%`. It rejects unknown schemas before
   claim and inventories types, relations, routines and other namespaced user
   metadata. Adversarial ordinary `pgxforeign` schema/table and standalone public
   enum/domain/range fixtures prove no ownership marker, no django_migrations
   table, and no reset of an existing synthetic row. The known-owned nonempty
   reuse regression remains green. All probes create/drop only their exact
   disposable task-owned database; no unknown owner database is inspected/reset.
2. Additive migration 0003 validates bounded original UTF-8 text using PostgreSQL
   `IS JSON WITH UNIQUE KEYS` before the old JSONB conversion trigger. It rejects
   duplicate acknowledgement/question/nested pointer keys and escaped aliases
   across ORM, bulk_create and raw SQL. This predicate checks nested objects;
   see the [official predicate documentation](https://www.postgresql.org/docs/17/functions-json.html#FUNCTIONS-SQLJSON-CHECK).
3. Migration 0003 also aligns the valid-ID column with Python 3.13: no C0/C1
   control characters or leading/trailing Python whitespace (including NBSP).
   Invalid original IDs persist only in original_row with NULL in external_id.
   Coverage includes all 29 Python whitespace characters, C0/C1 controls, all
   three insert paths, exact question preservation, and valid interior whitespace,
   opaque IDs and Arabic IDs. No source trimming or normalization.
4. The guard also refuses a known-owned old 0002 schema until the new duplicate
   validation trigger is installed/enabled. This regression first failed once on
   each PG version (guard incorrectly succeeded), then passed after the readiness
   check. Published migrations 0001/0002 are byte-for-byte unchanged.

The numeric contract proposal was held before publication per leadership.
See [NUMERIC_DECISION.md](NUMERIC_DECISION.md). Current parser and storage types
are unchanged: the fourth review defect remains open, not skipped or accepted.

## Registered suites and real commands

The corrective suites contain **19 pure** methods (11 contracts + 8 guard config)
and **25 DB** methods (21 existing + four corrective methods). The fourth new
registered DB method is old-schema readiness, not the held numeric proposal.
There are no skip/expected-failure decorators. B6 explicitly runs both actual DB
labels; C6 explicitly runs both actual pure labels on Windows and Ubuntu.

```text
.venv/bin/python -B -m unittest tests.wave7_foundation.test_contracts tests.wave7_foundation.test_guard_config -v
.venv/bin/python /tmp/wave7-e5-control.py run 17 .venv/bin/python manage.py test tests.wave7_foundation.test_database tests.wave7_foundation.test_review_regressions --noinput --settings=config.settings.wave7_test --verbosity=2
.venv/bin/python /tmp/wave7-e5-control.py run 18 .venv/bin/python manage.py test tests.wave7_foundation.test_database tests.wave7_foundation.test_review_regressions --noinput --settings=config.settings.wave7_test --verbosity=2
```

Working-tree verification: 19 pure PASS; 25 DB PASS on each server, zero
failures/errors/skips. Final committed-head counts, SHA, migration checks and
remote CI links belong to the PR handoff; a working-tree run is not presented as
a clean-head result. Logs are private under `/tmp/fatwa-wave7-e5-evidence/`.

Fresh independent rereview and numeric decision are pending. Windows/remote CI
are not presumed green. Combined Wave7/browser/source acceptance NOT_RUN.
Public/base settings, middleware, security/auth/session/admin, root dependencies,
other lane code, main and existing Wave6 worktree are unchanged.
NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED.
