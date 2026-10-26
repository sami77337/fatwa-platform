# FAST8 prepared-review validation

Base: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (Draft PR #134).
Lane: `codex/20261026-fast8-prepared-review-pc1`.
Required PR base: `codex/20261026-fast7-ci-integration-pc1`.

## Executed locally

Python 3.13.15 on Windows. Standard-library focused command:

```text
python -B -m unittest discover -s tests/fast8_prepared_review -q
Ran 20 tests; OK; zero skips.
```

Directly affected tests, using existing Django 5.2.18 environment
`C:/Users/Abu AL-yazeed/fatwa-platform/.venv/Scripts/python.exe`:

```text
python -B manage.py test tests.fast8_prepared_review.test_services tests.fast8_prepared_review.test_cli tests.workflow_invariants.test_engine tests.workflow_rehearsal.test_services tests.editorial_workbench.test_batches tests.prepared_pipeline.test_batches --settings=config.settings.test --noinput --verbosity=1
Ran 64 tests; OK; zero skips; system check: zero issues.
```

The 64 total includes the same 20 new tests, not 84 distinct tests. No browser/UI
route changed; no local browser or PostgreSQL test was needed or claimed for this
pure adapter. CI evidence must be checked separately on the pushed commit.
Shared CI YAML is untouched; its historical suite results do not establish that it
automatically collects the new lane tests.

Ruff 0.17.0 check and format-check passed on the owned files, using
`--no-cache`. `git diff --check` passed. No new package or service was installed.

Initial red evidence: 12 service tests could not find the not-yet-implemented API;
the three initial CLI tests failed before the CLI existed. Both passed after
implementation. Formatting initially identified three unformatted files; corrected.
One initial Django command used `tests.fast8_prepared_review` as a package selector;
Python namespace discovery raised `TypeError` for `tests.__file__ = None`, before
running tests. The explicit module command above passed, without shared changes.
Global Python has no pytest; unittest is the repository-compatible runner used here.

## Fixture identity and executable output

Only `apps/editorial_workbench/batch_fixtures.py:synthetic_inputs` is used. All content
is explicitly fabricated and already present at the base SHA. No owner archive,
private record or external service was accessed.

| Batch | Bytes | SHA256 |
| --- | ---: | --- |
| synthetic-csv | 719 | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` |
| synthetic-json | 620 | `d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec` |
| synthetic-jsonl | 714 | `e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363` |
| synthetic-malformed | 13 | `d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086` |

11 existing rows, four existing receipt drafts; no invented row for the malformed
batch. The default scenario produced 65,289 UTF-8 bytes including its final LF,
SHA256 `bb67af2430aa9b64ca1e676a8ea691040ecef9b553b76bd1b63161a8319dc7a5`.
Repeated subprocess runs returned identical bytes.

The 12 default attempts produced five PROJECTED, six REJECTED and one NOT_CONNECTED.
Diagnostics prove: completing review before starting fails; preparation enters
`draft_preparation`; publishing fails; the four existing review edges work; repeating
completion fails; missing title prevents preparation readiness; cross-dimension join
is NOT_CONNECTED; stale snapshot and changed source fingerprint fail. No answer is
added. Every rejected attempt preserves its complete before/after state.

## Review and release limits

One independent GPT-6 Astra/high review completed after implementation and the initial
19 new tests passed. It found one P2: aggregate request bytes were checked only after
full JSON allocation, allowing repeated aliased strings to expand excessively. The
new `test_repeated_large_strings_reject_before_full_serialization` failed before the
fix and passed after switching to bounded incremental UTF-8 encoding. No other
substantive findings or deferred minors. One agent completed, zero active.

No schema changes or migration plan required. Rollback is removal/revert of this
isolated lane commit; existing services and routes are unchanged.
Reference-to-Wave7 and preparation-to-review joins: NOT_CONNECTED.
Owner transition contract: NOT_SUPPLIED. Real source/PostgreSQL acceptance: NOT_RUN.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.
