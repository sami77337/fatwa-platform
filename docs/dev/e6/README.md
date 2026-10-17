# E6 synthetic acceptance

Wave6 ownership: new tests in `tests/acceptance/wave6/` only. No E4/E5 files,
root dependencies, routes, source snapshots, or catalog production code changed.

The runner creates/destroys a Django TEST database, migrates the actual PostgreSQL
schema, and seeds 47 fabricated headings (two roots and 45 children). The browser
uses Django's static-files-aware `StaticLiveServerTestCase`, SSR templates,
installed static assets and JSON API. It does not require `STATIC_ROOT` or
`collectstatic`; the shared E6 server is also exercised by HTTP asset regressions.
There is no HTML overlay. Editorial rows come from the actual no-argument
`build_preview_rows()` wrapper. No clip is fetched, clicked or played.

## Install and execute

From checkout root, use the existing Python pins and Node 24. No npm dependency.
Example on an otherwise unused Cloud disposable Docker service:

```sh
UV_CACHE_DIR=/tmp/e6-uv uv venv --python /usr/bin/python3.13 .venv
UV_CACHE_DIR=/tmp/e6-uv uv pip install --python .venv/bin/python --no-deps --index-url https://pypi.org/simple -r requirements.txt
docker run --detach --rm --name fatwa-e6-synthetic --publish 127.0.0.1:55466:5432 --env POSTGRES_DB=e6_synthetic --env POSTGRES_USER=e6_synthetic --env POSTGRES_PASSWORD=e6_disposable_only postgres:18-bookworm
export E6_SYNTHETIC_ONLY=1 PGHOST=127.0.0.1 PGPORT=55466
export PGDATABASE=e6_synthetic PGTESTDATABASE=test_e6_synthetic
export PGUSER=e6_synthetic PGPASSWORD=e6_disposable_only
node --test tests/acceptance/wave6/cdp.test.mjs
.venv/bin/python -m unittest tests.acceptance.wave6.test_guard -v
.venv/bin/python tests/acceptance/wave6/run.py
.venv/bin/python tests/acceptance/wave6/run.py --assets
.venv/bin/python tests/acceptance/wave6/run.py --regressions
E6_BROWSER=/usr/bin/chromium E6_ARTIFACTS=/tmp/e6-browser-results .venv/bin/python tests/acceptance/wave6/run.py --browser
docker stop fatwa-e6-synthetic
```

The sample password is disposable synthetic test configuration, not an owner
credential. Use unique service/port/database names starting `e6_synthetic` and
`test_e6_synthetic` when running concurrently. A missing acknowledgement, non-PG
engine, non-loopback host or other database prefix fails BEFORE database setup.
Do not invoke these modules with the unguarded existing matrix defaults.

The browser accepts a literal loopback origin, checks the fabricated inventory
before launching, and starts Chromium with its sandbox enabled. `E6_BROWSER` is
one executable path; it cannot supply flags. It blocks/reports external requests,
writes and media requests. No security configuration or sandbox bypass is allowed.
No automatic fallback converts unavailable Chromium into acceptance.

## Evidence and gates

- `run.py`: eight service/fixture tests, real Django/PostgreSQL; these are **not**
  browser interactions.
- `run.py --assets`: two real loopback live-server tests. Five catalog assets
  must return 200, executable JavaScript/CSS MIME and exact original file bytes;
  a nonexistent asset must return 404. The browser performs the same five-asset
  preflight before launching; bad assets fail the gate before engine startup.
- `run.py --regressions`: one API/SSR consistency regression, RED on baseline.
  This is an open E4 defect, not an expected failure or a passing waiver.
- `run.py --browser`: one mandatory Django browser gate, executing nine named
  CDP journey cases. Node exits 2 on startup BLOCKED, 1 on interaction failure;
  either fails the Django test and CI. Zero cases or missing engine cannot pass.
- `cdp.test.mjs`: six transport/request-policy unit tests; not browser acceptance.
- `test_guard`: six database-target safety tests, no database connection.
- `browser-result.json`: SHA, dirty paths, command, OS/Node/browser versions,
  per-case PASS/FAIL/NOT_RUN, zero fabricated skips, sanitized network trace and
  console/runtime errors. Screenshots are emitted only after actual attachment.

Browser cases cover desktop RTL/native keyboard, three Arabic modes, root/depth/
children filters, search paging/detail/history/reload/clear and PR47 basic links,
empty-query/filter-only consistency, empty results, a CDP-injected one-shot 503
and retry, review filter/page/detail/return/history/reload, missing/invalid media
and unresolved references, 390/320 CSS-pixel viewports, and network/console audit.
Fault injection affects only the intercepted synthetic browser request. Actual
HTTP 400 error pages are deliberate and do not count as JS console exceptions.

This lane targets the pinned baseline. Browser interaction code
is **unverified in a working engine** until the environment sandbox gate clears.
It contains strict assertions and is not an acceptance claim. The assembled-SHA
run must wait for E1–E4 integration. PR51 hooks are now prepared from actual head
`feb70f0fe9d0fe71765044045bc5924aa175f676`: `#batch`, allowlisted `default/mixed`,
`.original-text`, repeated `SYN-P01`, blocked `SYN-M03` and the actual GET links.
After integration, the required commands are:

```sh
.venv/bin/python tests/acceptance/wave6/run.py --review-batches
E6_ARTIFACTS=/tmp/e6-assembled .venv/bin/python tests/acceptance/wave6/run.py --browser --review-batches
```

The first command runs three actual loopback HTTP batch tests. It was verified
against an untouched PR51 code snapshot with only E6 test files overlaid; this
is not the final combined-SHA test. The second adds a tenth mandatory browser
journey for batch switching, exact whitespace, duplicate-ID isolation, filter/
page/detail/return/history/reload and clear retaining the chosen batch.
Missing E2 selectors fail; there is no optional fallback. Without this explicit
integration mode the report keeps `review_batch_acceptance: NOT_RUN`.
E5/coordinator must wire these exact commands
and capture `E6_ARTIFACTS` from the guarded synthetic service job; no root runner
or workflow edits are included here. Do not feed these DB tests to port-1 D6.

Real-source acceptance: NOT_RUN, no owner source service/archive used. Windows:
NOT_RUN. Independent review: NOT_PERFORMED. NOT_DEPLOYED / GATES_HOLD.
