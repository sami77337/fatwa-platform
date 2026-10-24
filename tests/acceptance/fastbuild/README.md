# Fastbuild real-browser acceptance

QA additions originally based on PR #96's published parent branch
`codex/20261024-fastbuild-editorial` at
`b1653b20584052f36fba1b59565c7ed57d688215`. FAST2 integration also covers the
queue from PR #98 and prepared batches from both PR #99 commits. Integration
adjustments here change acceptance tests only.

The implementation reuses Wave7's protected CDP transport and keyboard helper.
The default runner serves the actual Django WSGI application on an ephemeral
literal loopback port, preserving middleware, local-only guards, templates and
immutable service fixtures. `SimpleTestCase` forbids database connections,
including in the server thread. There is no HTML/API overlay or mock browser.

Execution plan: add reusable browser scenarios and request/result policy tests;
run editorial and directly affected regressions; attempt the explicit catalog
guard; independently review; commit and open one draft against the verified parent.

From the repository root (existing Python 3.13 dependencies, Node 24+, Chrome or
Chromium installed; no npm packages or browser downloads):

```powershell
python tests/acceptance/fastbuild/run.py
node --test tests/acceptance/fastbuild/policy.test.mjs tests/acceptance/wave7/cdp.test.mjs tests/acceptance/wave7/keyboard.test.mjs
python manage.py test tests.acceptance.fastbuild.test_runner tests.editorial_workbench.test_services tests.editorial_workbench.test_views tests.editorial_workbench.test_persisted --settings=config.settings.test
python -m ruff check tests/acceptance/fastbuild
python -m ruff format --check tests/acceptance/fastbuild
```

`FATWA_FASTBUILD_BROWSER` accepts one executable path, with no extra flags. Default:
Chrome's standard Windows installation or `/usr/bin/chromium` on Linux. Sandbox,
web security and CSP remain enabled. A temporary dedicated browser profile is
removed after exit. A 180-second watchdog closes the transport/browser ahead of
Python's 240-second timeout, leaving time for normal cleanup.

`FATWA_FASTBUILD_ARTIFACTS` selects a local report directory; default is
`<OS temporary directory>/fatwa-fastbuild-qa`. JSON records tested SHA, dirty paths,
fixture identity, named case results, blocked requests and browser version.
Screenshots and reports stay outside Git by default; do not commit profiles or
environment records. The Node entrypoint exits 0 PASS, 1 FAIL or 2 NOT_RUN.
The Python/Django test wrapper exits 1 for any unsuccessful browser test,
including NOT_RUN (read the JSON for the distinction); `run.py --catalog`
exits 2 when its ownership/configuration preflight denies execution. Unselected scopes are
explicitly listed; partial execution never becomes acceptance PASS.

Fourteen editorial cases cover Arabic RTL, nine original source-bound records
plus eleven prepared rows, keyboard
Tab/Enter/select navigation and visible skip-link focus, filtered return links,
sparse revision selection, reverse/same comparison, snapshot focus/back/forward,
source whitespace, empty/malformed/missing records, missing drafts, reference
status limits, expanded source/diff details and actual 320/375 CSS-pixel layouts.
The batch case checks all four original input hashes, exact row navigation,
rejected duplicate isolation and preserved selection. The queue case opens
revision 7 of the same record in the workbench and returns to filtered results.
Queue and batch views also receive real 320/375 CSS-pixel checks. The catalog
allowlist includes only the exact pinned `django_htmx/htmx-2.min.js` asset in
that asset directory; foreign requests, other htmx paths and writes stay denied.
The network gate intercepts before navigation and blocks foreign origins, writes,
media and routes outside the QA allowlist. Unexpected HTTP errors, console errors
and runtime exceptions fail the run. Expected recovery responses assert HTTP
400/404 as well as usable content.

## Optional real PostgreSQL catalog gate

```powershell
python tests/acceptance/fastbuild/run.py --catalog
```

This reuses `tests.acceptance.wave7.target`, `Wave7TestRunner`, `E6LiveServer` and
`seed_reference_catalog`; there is no alternate database backend. It requires the
existing explicit E6 acknowledgement, synthetic write guard, owned loopback PG
17/18 base named `wave7_synthetic_e6_*`, its matching test name and restricted
Wave7 role. It never enables these flags, provisions a service, initializes a
base or resets an occupied database. The existing runner creates and cleans up
only its own fresh test database. Configure the existing Wave7 environment before
running; do not point at another lane's database.

Five catalog cases cover actual SSR/API tree traversal, Arabic search,
breadcrumbs, native clear/search recovery, browser back/forward, reloadable
detail routes, 320/375 layouts and the network gate. Public node IDs are source
row IDs 1/2/3, distinct from database primary keys 7001/7002/7003.

Synthetic fixture identities:

- `fixtures.synthetic_payload()` SHA-256:
  `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb`.
- Serialized immutable history intake SHA-256 (not original source-file bytes):
  `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0`.
- Catalog `wave7-fixed-fabricated-fixture`: three titles, one root, depth two;
  namespace `wave7-synthetic-toc`, edition `wave7-synthetic-edition-v1`, archive
  hash `b` repeated 64 and input hash `a` repeated 64 (asserted synthetic labels).

Original PR #100 validation on Windows/Chrome, before FAST2 integration:
12 editorial browser cases PASS; catalog's
five cases NOT_RUN (`E6_ACCEPTANCE_OPT_IN_REQUIRED`, no owned E6 PostgreSQL
configuration supplied). Also: 27 Python regressions (25 affected workbench plus
two runner failure paths) and 11 Node policy/transport/keyboard tests PASS;
Ruff lint/format and Node syntax checks PASS. One independent final review found
no remaining functional blocker; its mobile/lifecycle and documentation findings
were addressed. No persisted-workflow, real owner source ZIP, scholarly
approval, private-case or publication acceptance is claimed. Browser assertions
remain executable when the approved database is supplied. Application defects
belong to the coordinator; this lane does not patch application code.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED / GATES_HOLD.
