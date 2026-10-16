# Wave6 E2: reusable synthetic worklist composition

Base: `codex/20261017-wave5-review-worklist` at
`b5de539237de0cd12b91b0705a3cb92014bfe98b`.
Only E2 files change. The lane PR records the exact published head.

`compose_synthetic_batch(raw: bytes, *, synthetic_fixtures_only: bool = False,
reference_map, bridge_config, catalog) -> tuple[IntegratedPreviewRow, ...]`
rejects omitted/false/non-boolean acknowledgement before parsing or pipeline work.
It accepts a bounded C1 JSON envelope and explicit caller dependencies. No
payload field, question text or external ID supplies source identity. Limits are
1,000,000 input bytes, 1,000 rows and 100 references per row. Duplicate keys,
invalid UTF-8/surrogates, extra envelope fields and excessive bounds reject.

The existing no-argument `build_preview_rows()` wraps the new composition for
`default`. The same GET/HEAD loopback worklist also offers an allowlisted `mixed`
batch. There are no uploads, arbitrary paths, POST processing or persistence.
`default` and `mixed` deliberately share `SYN-P01` with different exact question
strings. The selected batch scopes detail lookup; batch, query, status, issue,
page and page size survive paging/detail/return. Clear filters retains the batch.
Native select/link/form controls remain keyboard accessible. Original question
spaces, Arabic marks, tabs and newlines remain intact; `pre-wrap` exposes them.

D1 runs on the exact original bytes. Rows D1 marks blocked stay visible without
drafts or citations; only eligible originals enter D3. This prevents D3's
whole-envelope duplicate/malformed-pointer rejection from hiding valid rows.
Eligible rows are joined by order and exact ID; original pointers, all six C2
identity fields, explicit numeric mapping and complete evidence/provenance still
must match. Adapter citation markup is never trusted. Supplied pins are caller
assertions, not evidence of inspecting an owner archive. Existing #49 fault
injection/escaping tests are unchanged.

## Regression and verification evidence

Host: selected published Cloud task environment reported ready:
`ccarenv_b64_Y2NhcmVudl9mYWE2OTJhMjg0MTQ4MTkxODlmNmI4ZTI5NDYyYzMwNA`.
A separate Cloud task ID/URL and published flag are not exposed by runtime tools.
Python 3.13.5 (`/usr/bin/python3.13`), Node 24.19.0, uv 0.12.23.
The venv interpreter below is a symlink to `/usr/bin/python3.13`.

Dependency setup (existing pins, no root dependency changes):

```sh
UV_CACHE_DIR=/tmp/fatwa-e2-uv uv venv --python /usr/bin/python3.13 /tmp/fatwa-e2-venv
UV_CACHE_DIR=/tmp/fatwa-e2-uv uv pip install --python /tmp/fatwa-e2-venv/bin/python --no-deps -r requirements.txt
```

The initial uv attempt could not write the default home cache; selecting the
writable disposable cache resolved it without permissions/security changes.

Baseline: the existing three editorial modules passed 44/44 (0 skips).
RED: new `tests.editorial_demo.test_synthetic_batch` ran 10 methods, with 14
failing assertions/subcases and 1 error. The callable was absent, `batch=mixed`
returned 400, and the duplicate-ID wrapper raised `ValueError: Duplicate
external_id`. The invalid-selector test already passed and is retained evidence.
GREEN: 11 new methods plus all 44 existing editorial tests pass, 55 total,
0 failures/errors/skips. New tests use unseen IDs/text, mixed media/missing maps,
malformed/non-object/duplicate blocked rows, caller-map disagreement, bounds,
acknowledgement, repeat-call isolation and batch/filter/page/detail-return state.
Django SimpleTestCase rejects database use; network and SQLite are also guarded.

Actual verification commands, run from checkout root:

```sh
PGPORT=1 /tmp/fatwa-e2-venv/bin/python manage.py test tests.editorial_demo.test_preview tests.editorial_demo.test_pipeline_preview tests.editorial_demo.test_worklist tests.editorial_demo.test_synthetic_batch --noinput --settings=config.settings.test
/tmp/fatwa-e2-venv/bin/python tools/dev/qa.py system
/tmp/fatwa-e2-venv/bin/python tools/dev/wave3_qa.py --standalone --require-integrated
/tmp/fatwa-e2-venv/bin/python tools/dev/wave4_qa.py --wave3 --json /tmp/e2-wave4-summary.json
/tmp/fatwa-e2-venv/bin/python tools/dev/qa.py node
/tmp/fatwa-e2-venv/bin/python -m unittest discover -s tests/dev -p 'test_*.py' -v
git diff --check
```

Results (overlapping suites, do not sum as distinct tests):

| Command | Actual result |
| --- | --- |
| Explicit editorial labels | 55 passed, 0 skipped |
| system | PASS, 0 issues |
| C6 standalone | intake 11 + drafts 17 + reference links 37 passed; 0 skipped |
| D6 with C6 | PASS: D1 28; D2 16+9+19; D3 37; D4 Django 4 + Node 26; D5 18; nested C6 11+17+37 |
| Node non-browser | 94 registered, 85 passed, 9 skipped, 0 failed |
| Dispatcher discovery | 42 collected, 40 passed, 2 Windows-only skipped |
| diff check | PASS |

Node skips: unavailable owner archive (1); Windows-only CMD/PowerShell launcher
checks (8). No launcher startup or source import was executed. Dispatcher skips
are the two Windows CMD execution tests. A convenience invocation using only
`manage.py test tests.editorial_demo` failed discovery before tests because
`tests` is a Python 3.13 namespace package; the explicit module invocation above
is the existing supported project contract and succeeded.

## Integration handoff

E5 must add the exact no-DB label `tests.editorial_demo.test_synthetic_batch` to
D2's Django list in `tools/dev/wave4_suites.json` (or the assembled equivalent).
It currently is **not** discovered by the unchanged D6 manifest. Run all four
explicit labels above with port 1; never mix E3 DB labels into that run.
E2 does not own/edit the shared manifest, workflows, routes or root dependencies.

Synthetic examples for E1/E3/coordinator: `SyntheticBatchTests.fresh()` uses
`UNSEEN-619`, exact `"  سُؤَالٌ جديد\tبِعلاماته\nوسطره  "`, example.invalid HTTPS
media and the explicit synthetic C1 pointer supplied by `_synthetic_dependencies`.
Tests are executable examples and do not require real data. The `mixed` batch
contains valid, invalid-port, malformed-reference and missing-media records.

E1/E3 Wave6 heads were absent when checked during this lane run. Combined-SHA
rerun after their assembly is **NOT_RUN / pending coordinator**, not implied by
passing compatibility with pinned-base D1/D3. PostgreSQL 17/18, Windows CI, real
browser/E6, full importer/E5 and real-source acceptance are NOT_RUN in E2.
No independent review or product/source acceptance is claimed. Source archives
were not opened, source databases were not used, and no source reimport occurred.
No migration or security configuration changed. NOT_DEPLOYED / GATES_HOLD.
