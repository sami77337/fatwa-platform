# Wave6 E4 catalog increment

Base: `b5de539237de0cd12b91b0705a3cb92014bfe98b`.
Branch: `codex/20261017-wave6-e4`. The exact published head is recorded in the Draft PR and Issue50 handoff; this file belongs to that commit.

## Behavior and contracts

- A default `/fiqh` request browses roots. An explicit search (`q` present, including empty/whitespace), or any selected root/depth/has_children filter, renders search results in SSR. Search URLs reload as native SSR pages, preserving the existing basic fallback.
- The API's unfiltered empty search still returns an empty page. A blank/whitespace query with at least one explicit filter now returns the bounded matching headings in all three modes. A nonblank query normalized to nothing (marks/tatweel alone) still returns no matches. Invalid/missing/nonroot scope is validated even for empty text.
- SSR pagers preserve filter-only state. Native detail links carry validated search state plus a bounded `search_offset` (node/branch routes only); the return link restores the original query bytes, filters and search page independently of child pagination. No arbitrary return URL is accepted.
- Clearing resets text, mode, scope, depth and child controls together with the URL. Paging/retry restores the submitted controls. Failed searches retain a bookmark and retry after history restoration; newer root/detail navigation aborts stale searches. The PR47 basic-link construction remains intact and tested.
- A 503 SSR page offers a native retry link to the same bookmark. Unknown/duplicate/excessive parameters and invalid bounds retain controlled errors; API errors remain JSON. Search/source identity, original Arabic titles, hidden edition UI and native keyboard controls are preserved.

No dependency, route, model, migration, other-lane production code, source input or source pin changes. No source reimport, owner data, media fetch, answer or approval operation.

## Regression evidence

Tests were written and executed before their corresponding fixes:

| Observation | RED | GREEN |
| --- | --- | --- |
| Blank filters skipped by service/SSR; ambiguous filter-only SSR silently empty | `test_e4_catalog` initial run: 5 tests, 6 assertion failures including subtests | Full owned and B6 suites below |
| Clear left selected filters visible; pager stored unsent controls | catalog Node run: 25 tests, 23 pass, 2 fail | Full Node suites below |
| Native detail lost exact search/page state | focused suite: 6 tests, 5 pass, 1 fail | Full suites below |
| Failed search lacked bookmark/retry after navigation | Node run: 26 tests, 25 pass, 1 fail | Full suites below |
| Explicit empty SSR search unexpectedly browsed roots | focused test: 1 fail | Full suites below |
| 503 lacked native retry; late search could replace newer root URL | focused Python/Node runs: 1 failure each | Full suites below |
| Search-context leaf message and ancestor links lost useful detail/return semantics | focused detail test: 1 failure for each observed defect before fixes | Full suites below |

Two existing expectations were updated for the intended change: valid root-only search now executes its predicate, and a pager restores its submitted controls before a new edited submission. All other existing regressions remain.

Test-development errors were corrected: the first synthetic PG fixture attempted a child before its second-edition parent existed (0 tests, setup error); the isolated runner initially lacked Django template-context capture (41 tests, 4 errors). Tests now assert rendered HTML/service calls without changing the runner. These were not product passes.

## Executed Linux evidence

Runtime: `/usr/bin/python3.13` 3.13.5 via a uv-created venv at `/workspace/e4-venv`; Node 24.19.0. Existing exact `requirements.txt` pins installed with uv from `https://pypi.org/simple`, `--no-deps`. Cache redirected to `/tmp/e4-uv-cache` after the default cache proved read-only. No credentials or security settings changed.

Python below means `/workspace/e4-venv/bin/python` (the explicit Python 3.13 venv).

| Command | Result |
| --- | --- |
| `python manage.py test tests/integration/api tests.integration.ui.test_templates tests.integration.ui.test_discovery --noinput --settings=config.settings.test` | 47 pass, 0 fail, 0 skip |
| `python -B tests/integration/api/run_isolated.py` | 41 pass, 0 fail, 0 skip; database connection creation forbidden by runner |
| `python -B tests/integration/api/run_c4_synthetic.py` | 5 pass; supplementary in-memory predicate logic, not PostgreSQL acceptance |
| `node --test tests/integration/ui/adapter.test.mjs tests/integration/ui/catalog.test.mjs tests/integration/ui/tree.test.mjs tests/integration/django-api.test.mjs` | 62 pass, 0 fail, 0 skip; DOM/event and adapter tests, not browser acceptance |
| `python tools/dev/qa.py node` | 117 discovered, 108 pass, 0 fail, 9 skip: owner archive unavailable (1), actual Windows CMD/PowerShell invocation/parser checks unavailable on Linux (8) |
| `python tools/dev/qa.py system` | PASS, no system-check issues |
| Full existing B6 command below, PG18.6 and PG17.11 separately | 146 pass, 0 fail, 0 skip on each version |
| `git diff --check` | PASS |

Full B6 command (synthetic DB only):

```sh
python manage.py test tests/reference tests/public_site tests/security tests/integration/api tests/integration/ui tests.integration.source.test_read_only_commands tests.integration.test_site --noinput --settings=config.settings.test --verbosity=2
```

On each disposable service, also passed `manage.py check --database default`, `makemigrations --check --dry-run` (no changes), `migrate --noinput` (both existing migrations) and `migrate --check`, all with `--settings=config.settings.test`.

Isolation: containers `fatwa-wave6-e4-pg18` and `fatwa-wave6-e4-pg17`, loopback ports 55464 and 55467; synthetic database `e4_synthetic`, Django-created/destroyed `test_e4_synthetic`. No owner/sibling database. Images `postgres:18-bookworm` digest `sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c` and `postgres:17-bookworm` digest `sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826`.

The new actual-PG module uses 60 synthetic headings across two editions with repeated source IDs and different topology. It compares 483 query/filter combinations through API and SSR, original Arabic projections, paging/reload, absent matches, depth-five paths, bounds and edition isolation. Its measurement test issues five requests per interface, asserting only SELECTs and exactly 4 API / 6 SSR queries. Observed full-B6 samples (wall clock ms, concurrent synthetic PG runs; no real-source extrapolation):

- PG18 API `[17.000, 14.114, 13.224, 15.864, 18.079]`; SSR `[21.899, 21.549, 22.841, 23.337, 20.664]`.
- PG17 API `[20.466, 16.171, 16.645, 24.742, 16.536]`; SSR `[27.653, 23.452, 23.672, 23.578, 24.575]`.

Sanitized command logs are retained under `/tmp/e4-*.log` in this Cloud environment. Committed-head reruns and CI status belong to the PR/handoff, not an invented CI pass here.

## E5 and E6 integration handoff

E5: no shared-root changes needed. Existing B6 `tests/integration/api` and `tests/integration/ui` discover these additions. New no-DB label: `tests.integration.api.test_e4_catalog` (8 tests). Real-PG-only label: `tests.integration.ui.test_e4_postgres` (3 tests); never add it to C6/D6's port-1 runner. Existing D4 label remains unchanged. Final combined matrix is coordinator-owned.

E6: PR52 fixture/test at `fa2b123e967e0550e4c2570d6770e8577aa16e95` was inspected read-only. Its exact `q=&depth=2&has_children=false&limit=20` API/SSR inconsistency is covered by the E4 regression and real-PG filter-only/pagination matrix. No E6 files merged or modified. E6 reports its browser sandbox blocked; this lane does not bypass it. Use its own isolated synthetic service. Stable hooks remain `#search-form`, `#search-query`, `#search-mode`, `#search-scope`, `#search-depth`, `#search-has_children`, `#clear-search`, `#search-results`, `#basic-link`, `#error`, `#status`, `#tree`, `[role=treeitem]`, `#reference-content`. Native SSR form uses `#query`, `#mode`, `#basic-depth`, `#basic-has_children`; details return link text is `العودة إلى نتائج البحث`, retry is `إعادة المحاولة`, clear is `مسح البحث والمرشحات`. SSR search/filter reloads intentionally remain native fallback pages. Node fixtures are not browser evidence.

NOT_RUN: real desktop/mobile browser, Windows execution, combined E1–E6 SHA, real-source acceptance/performance, full importer acceptance (E5), fresh independent review of the race follow-up. Browser sandbox/security was not altered. CLI GraphQL PR lookup returned Forbidden; the already connected GitHub connector successfully checked for duplicate PRs without a new credential grant.

Environment ready ID: `ccarenv_b64_Y2NhcmVudl81MjI1MTE2ZDg4MjQ4MTkxYjU4OGZkMDYyYTJiYTIzZQ`; environment publication/name metadata, task URL/ID and subscription usage are not exposed here. Actual E4 process active; no child agents launched. `USAGE_NOT_OBSERVED / NOT_DEPLOYED / GATES_HOLD`. No independent product/source acceptance is claimed. Independent review of the earlier head returned FIXES_REQUIRED; the follow-up awaits independent re-review.

## Independent review follow-up: navigation races

The coordinator supplied an independent Astra FIXES_REQUIRED review of
`411965fc94329e0c206101144a788351b63e245e`: a delayed search could override
Enter activation of a branch, and a delayed detail could override a newer search.
Both were reproduced locally with deterministic deferred promises before changes:
`node --test --test-name-pattern='E4 review R[12]' tests/integration/ui/catalog.test.mjs`
reported 2 tests, 0 pass, 2 fail, with the wrong URLs explicitly asserted.

Search/tree requests now invalidate each other at request creation, using the
existing AbortController identity checks to reject late successes and errors even
when transport ignores abort. Synchronous collapse/leaf/clear actions also cancel
outstanding work and reset busy state. No keyboard mappings or history format
changed. Complementary leaf-selection and clear-during-detail cases each failed
before their cancellation calls were added.

`node --test --test-name-pattern='E4 review' tests/integration/ui/catalog.test.mjs`
now passes 3 tests (8 deterministic completion schedules: branch expand/collapse
with late success/failure; new search with late detail success/failure; synchronous
leaf and clear with late detail). They assert URL, history snapshot, selected
node, focus, busy state and absence of stale errors. Existing error/retry,
history/reload, native keyboard and PR47 cases remain in the full suite.

Follow-up changes are only `apps/reference/static/reference/catalog.js`,
`tests/integration/ui/catalog.test.mjs`, and this evidence file. Same branch/PR55;
no amend/force-push, no other lane changes, no browser-security changes. The
original independent review is acknowledged; these fixes are author-verified and
require fresh independent re-review. Final commit/CI/counts are in the PR/handoff.

## Independent re-review follow-up: Home await continuation

The coordinator reported that independent re-review of
`c21bebbd9e1cd7d97646ca19f6f2d6fab304f990` closed the original two races but
found a remaining P2 in `homeCatalog`: its caller continued after an unsuccessful
or superseded `chooseRoot`, changing URL/basic-link/focus after newer actions.
The new follow-up remains author-verified and requires independent re-review.

Deterministic RED/GREEN command:

```sh
node --test --test-name-pattern='E4 (Home|current Home)' tests/integration/ui/catalog.test.mjs
```

The initial 14-case run had 1 pass / 13 fail: Home followed by each of search,
root selection, clear and Back, with delayed success, delayed failure or immediate
abort-aware AbortError (12 cases); a microtask-ordered case where child loading
succeeds before a newer root action (1); and an unaffected successful Home (1).
A separate current-Home failure/retry test also failed RED. Checking success alone
made 13/15 pass, but still failed the successful-child/late-caller case and retry.
The final 15/15 pass with zero fail/skip, alongside all prior tests.

Home now checks successful completion, disposal and a captured navigation version
before changing history, the fallback link or focus. Cancelling tree work advances
the version even for synchronous actions with no active transport. This protects
the outer caller as well as the adapter await. A current failure keeps its retry
button; retry restarts the complete Home action so successful retry can navigate
and focus normally. The internal retry callback is passed only by Home; other
branch retry behavior is preserved.

Narrow async-continuation audit: expand/search/openResult check request identity
after awaited adapter work; chooseRoot returns expand directly without later DOM
mutations; pop's awaited branches have no subsequent navigation mutations; start
checks child success and its catalog request before initialization. The existing
clipboard selection/disposal guard remains unchanged. No global cache, external
request, security setting, public route, source identity or other-lane edit.

Assertions cover URL/query, history snapshot/length, selected node, native fallback
link, focus, busy/status/error state, immediate AbortError, successful Home and
current failure/retry. Follow-up changes remain limited to catalog.js,
catalog.test.mjs and this E4 evidence file. Exact final head/CI/counts are in PR55
and the coordinator handoff.
