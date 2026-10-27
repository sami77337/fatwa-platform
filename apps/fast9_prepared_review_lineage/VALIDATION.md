# FAST9 lane validation

Date: 2026-10-27. Runtime: Windows, Python 3.13.15, Ruff 0.17.0.
Integrated source base: `0769f66e93fdf710ca55e9e68e87430a93f14c40`.
Branch: `codex/20261027-fast9-prepared-review-lineage-pc1`.
Final commit SHA and remote CI run links are recorded in the Draft PR handoff;
the implementation was tested in this worktree, not a sibling lane checkout.

## Executed

```powershell
python -B -m unittest discover -s tests/fast9_prepared_review_lineage -v
```

19 tests passed, zero skips/xfails. The row-inventory subtests exercise all 11
existing prepared cases; they are not counted as 11 additional test methods.

```powershell
python -B manage.py test tests.fast9_prepared_review_lineage.test_services tests.fast9_prepared_review_lineage.test_cli tests.fast8_prepared_review.test_services tests.fast8_prepared_review.test_cli tests.fast8_review_export.test_services tests.fast8_review_export.test_cli tests.fast8_packet_verifier.test_services tests.fast8_packet_verifier.test_cli tests.workflow_invariants.test_engine tests.workflow_invariants.test_cli tests.editorial_workbench.test_packets tests.editorial_export.test_services --settings=config.settings.test --noinput --verbosity=1
```

129 tests passed in 27.175 seconds, zero skips; Django system check: no issues.
This includes the 19 new tests, not 129 additional new tests. All selected classes
are unittest.TestCase or Django SimpleTestCase. No database setup or PostgreSQL
connection was used by this run.

```powershell
python -B -m ruff check --no-cache apps/fast9_prepared_review_lineage tools/fast9_prepared_review_lineage tests/fast9_prepared_review_lineage
python -B -m ruff format --check --no-cache apps/fast9_prepared_review_lineage tools/fast9_prepared_review_lineage tests/fast9_prepared_review_lineage
git diff --check
```

All passed. No root dependency, config, routes, CI, migrations or source fixture
files changed. Tests verify Unicode/CRLF, exact parent/row identities, duplicate
external IDs, absent drafts, stale tokens, changed source tokens, rejected bundle
members and a rehashed altered manifest, all three stock scenarios, development
guards, deterministic bytes, and preservation of input modification times.

## Reproducible default evidence

```powershell
python -B -m tools.fast9_prepared_review_lineage --synthetic-fixtures-only
```

Fixed input: existing `editorial_workbench.batch_fixtures.synthetic_inputs`,
`synthetic-csv`, row 1, `batch-synthetic-csv-1` / `SYN-CSV-1`; stock scenario
`rehearsal` remains a distinct unjoined case. No source-owner files involved.

| Item | SHA-256 |
|---|---|
| Parent payload | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` |
| Parsed prepared row | `0598e433692f151215645cb4fac62b86aace9f4fa5572ed905bbb7a6d5d9b434` |
| Prepared case | `f6afd425d07b321f4ed9ea27380465f12eee2490cd327eff604f893e8007131e` |
| Canonical workbench packet | `64f615e4ca56de6b4a610a6a4ca682ee13121fb42a262aafffae5986f56062c2` |
| Evidence stdout (77,761 bytes) | `265c29893fe9890d8736222f59df4c20e5ad872974da25bddda74fe5d8a12ba6` |

The record includes verified byte counts and hashes for four source-export and
three review-preview members. Default attempts: 12 total, 5 SUPPORTED (pure
projections), 6 REJECTED, 1 NOT_CONNECTED. These are synthetic diagnostic outcomes,
not failing tests, persisted review, scholarly conclusions or owner acceptance.

## Failures and unexecuted work

- Before implementation: first service collection failed with missing new module;
  seven CLI tests then failed because the new command was absent. Both were
  resolved by implementation. Final focused/affected runs have no failures.
- PostgreSQL: NOT_RUN. No preauthorized exact disposable target was supplied;
  no credential discovery, default database connection or migration attempted.
- Browser: NOT_RUN; this lane adds no UI or HTTP surface.
- Full unbounded Django suite: NOT_RUN; its database/browser prerequisites are
  not available for this lane. The affected offline suite above is the executed
  scope. The existing guarded opt-in PostgreSQL command is in README.
- Inherited remote B6/C6/D6: inspect the final SHA's actual runs in the Draft PR.
  Their explicit suite lists do not collect new FAST9 modules. A green run is
  inherited coverage, not evidence of this new lane's test execution.

## Independent review

One actual read-only reviewer agent (`lineage_review`, GPT-6 Astra, high) was
started after implementation and the 129-test affected run. It found no blocking
correctness/safety issues and independently passed 12 service tests plus 4 CLI
tests (16 total). It inspected the three temporary-file CLI tests without running
their writes. Its minor missing-validation-document note was resolved; a second
read-only documentation check confirmed the link and content. No review edits,
database or network access occurred.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING. Missing prepared-to-stock-workflow,
projected-review-to-export and persisted-review joins remain NOT_CONNECTED.
