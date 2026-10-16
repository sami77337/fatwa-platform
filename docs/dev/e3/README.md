# Wave6 E3 — synthetic adapter evidence

Base: `b5de539237de0cd12b91b0705a3cb92014bfe98b`, branch
`codex/20261017-wave5-review-worklist`. Producer branch:
`codex/20261017-wave6-e3`. Only E3-owned paths changed. The PR handoff records
the exact committed head; no merge, deployment, source import or owner data reads.

## Delivered behavior and trust boundary

- Exact C1 text maps and all six C2 pointer fields remain caller-configured.
  Numeric edition/row IDs are explicit integers, including at the Django adapter
  boundary; opaque strings and booleans cannot reach ORM coercion.
- `Heading` retains its existing type and positional constructor, with two optional
  trailing fields: `edition_key` and `source_archive_sha256`. Django supplies both
  from actual edition rows. The bridge suppresses citation/evidence when supplied
  catalog edition/archive pins conflict, in addition to namespace/book/input pins.
  Older snapshot constructors remain supported. Absent optional snapshot pins are
  caller assertions, **not independently inspected archive evidence**. Even matching
  DB hashes prove only that stored metadata matches the supplied configuration.
- Malformed individual pointers stay visible and unverified beside valid pointers.
  Object provenance preserves original key order and JSON values. A nonobject has
  no original fields: its complete JSON value is retained as
  `(("$invalid_pointer", value),)`; this diagnostic sentinel is never resolved.
  Invalid envelopes, duplicate JSON keys/row IDs and invalid reference lists still
  raise `ValueError`. Both raw entrypoints enforce 1,000,000 bytes before decoding,
  at most 1,000 rows and 100 references per row.
- Invalid adapter path/hash types produce unverified evidence. Citations retain
  original Arabic marks, the complete path and printed part/page, escape HTML,
  and explicitly describe a TOC heading, not a scholarly ruling.
- Per-row duplicate detection now counts exact textual pointers once instead of
  scanning the complete pointer list once per reference. No global cache exists.

## Execution and RED/GREEN

Observed environment: published-task environment supplied by parent, ID
`ccarenv_b64_Y2NhcmVudl9jZWIwOGY2ODQ0OTQ4MTkxOGVhNTRhNTcyYjM2MjQ5Mw`,
ready; independent publication metadata/task URL not exposed. Debian 13.6 Linux
x86_64; `/usr/bin/python3.13` 3.13.5; Node 24.19.0; Docker 28.4.0.
One E3 executor observed; other lanes/quota/usage not observed.

Setup used existing exact pins from PyPI, without changing root dependencies:

```sh
UV_CACHE_DIR=/tmp/e3-uv-cache uv venv --python /usr/bin/python3.13 /tmp/e3-venv
UV_CACHE_DIR=/tmp/e3-uv-cache uv pip install --python /tmp/e3-venv/bin/python --index-url https://pypi.org/simple --no-deps -r requirements.txt
```

The initial default uv cache was read-only; redirecting only its cache to `/tmp`
resolved this. No grants or system configuration changes. `gh auth status` reported
an invalid existing token; it was not modified. Git fetch/dry-run push worked;
publication uses the existing Git connection and GitHub connector.

Baseline pure suite: **37 passed**. Before production edits, the new regression
module ran 11 tests and failed (2 assertion failures, 8 error/subtest events):
oversized input accepted; malformed link aborts; malformed adapter metadata crashes
or verifies. Actual PG18 adapter RED ran 12 tests and failed (5 assertion failures,
1 error/subtest event): conflicting stored archive/key verified, opaque numeric
edition strings/booleans accepted, and string row ID raised `TypeError`.
These are unittest event counts, not counts of independent failing test methods.
Initial test-fixture attempts to mutate immutable rows were rejected by existing
DB triggers; final fixtures insert separate editions and preserve those triggers.

Final local results, zero failures/errors/skips:

| Actual command (`PY=/tmp/e3-venv/bin/python`) | Result |
| --- | --- |
| `PGPORT=1 $PY -m unittest discover -s tests/reference_links -v` | 50 passed |
| `$PY manage.py test tests.reference_links_db.test_catalog_adapter --noinput --settings=config.settings.test -v 2` | 12 passed on PG18.6; 12 passed on PG17.11 |
| `PGPORT=1 $PY -m unittest discover -s tests/prepared_pipeline -v` | 28 passed |
| `PGPORT=1 $PY manage.py test tests.editorial_demo.test_preview tests.editorial_demo.test_pipeline_preview tests.editorial_demo.test_worklist --noinput --settings=config.settings.test` | 44 passed (16 + 9 + 19) |
| `$PY tools/dev/wave3_qa.py --standalone --require-integrated` | content intake 11 + drafts 17 + links 50 = 78 passed |
| `$PY tools/dev/wave4_qa.py --wave3 --json /tmp/e3-wave4-summary.json` | PASS; D1 28, D2 44, D3 50, D4 Django 4 + Node 26, D5 18; nested C6 78; 248 executions including repeated suites |

PostgreSQL services are **separate synthetic cloud containers** `wave6-e3-pg18`
on loopback port 55483 and `wave6-e3-pg17` on 55473. Disposable database names
`e3_ephemeral` / `test_e3_ephemeral`, user `e3_synthetic`; no owner catalog used.
Images observed:

- PG18.6 `postgres:18-bookworm`, digest `sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c`.
- PG17.11 `postgres:17-bookworm`, digest `sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826`.

For each DB invocation explicitly set `PGHOST=127.0.0.1`, the port above,
`PGDATABASE=e3_ephemeral`, `PGTESTDATABASE=test_e3_ephemeral`, `PGUSER=e3_synthetic`
and the disposable test password supplied at container creation. Actual migrations
0001/0002 run on fresh test DBs. PG18 also passed Django database check,
makemigrations check/dry-run (no changes), migrate and migrate check using
`django.core.management.call_command`, with the explicit synthetic environment.
The new DB test's temporary table rename induces a real PostgreSQL read error and
rolls back immediately; no mocked ORM/service reads. Other lookup SQL is asserted
SELECT-only. A five-level path uses exactly six SELECTs; missing heading uses two,
missing edition one. DB uniqueness/parent/immutability constraints are exercised;
actual ambiguous DB rows cannot exist under this schema. Snapshot ambiguity is
also tested using two copies of actual adapter evidence.

## Lookup measurements and integration dependencies

`docs/dev/e3/measure_lookup.py` runs a synthetic 41,389-byte batch: 20,000 mappings,
10 rows × 100 distinct references, 10 timed repetitions plus one profile. Run with
the selected checkout on `PYTHONPATH`; baseline was extracted with
`git archive b5de539237de0cd12b91b0705a3cb92014bfe98b apps/reference_links` into `/tmp/e3-baseline`.

| Measured source | Median milliseconds | Full reference-list `.count` scans |
| --- | ---: | ---: |
| Pinned baseline | 24.921 | 1,000 |
| E3 increment | 26.720 | 0 |

This demonstrates removal of quadratic scans, **not a latency speedup**; the new
validation adds work. No extrapolation to real source performance. A deterministic
regression separately counts 2,000 mapping-key reads for 2,000 mappings while
resolving 1,000 pointers: one complete C1 map construction per invocation, not
one scan per pointer. Exactly 1,000 snapshot lookups occur, without a global cache.

E2/coordinator: pinned `apps/editorial_demo/integration.py::_reference` contains
`next(... for row in bridge.headings ...)` for every reference. That repeated
full-map scan is outside E3 ownership. Build its exact C1 index once per composition
without relaxing PR49's original-pointer/full-evidence comparison. E3's optional
Heading fields appear in `asdict(evidence)` on both D1/D3 paths; baseline E2 tests
pass, but final assembled E1/E2/E3 execution remains required.

E5 exact **DB-only label**: `tests.reference_links_db.test_catalog_adapter`.
Package initializer is included. Never add it to C6/D6's port-1 discovery.
Pure label remains discovery under `tests/reference_links`; the new pure module
is `test_wave6_contracts.py`. No shared-root dependency/route/workflow edits.

Ubuntu/Windows CI, full B6 matrix, full importer, final assembled browser execution,
real-source acceptance and independent review are **NOT_RUN by E3**. Existing
workflows do not yet wire the new DB label; E5/coordinator must do so after assembly.
Raw local logs are under `/tmp/e3-*.log`; bounded D6 report is
`/tmp/e3-wave4-summary.json`. They are ephemeral, and sanitized evidence is retained
here and in the PR. No browser or sandbox configuration changed.

`USAGE_NOT_OBSERVED / NOT_DEPLOYED / GATES_HOLD`.
