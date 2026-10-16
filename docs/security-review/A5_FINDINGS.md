# A5 — independent security and functional QA

2026-10-15. NON_PRODUCTION / NOT_DEPLOYED. Gate B NOT_PASSED; C/D/E HOLD;
Phase01 BLOCKED. No gate acceptance is asserted.

## Recorded result

| Evidence | Tests run | Pass | Fail | Not run |
| --- | ---: | ---: | ---: | ---: |
| Static source inspection | 9 | 9 | 0 | 0 |
| Synthetic real-adapter tests | 13 | 10 | 3 | 0 |
| Actual loopback HTTP | 19 | 18 | 1 | 0 |
| Isolated Django / no DB | 0 | 0 | 0 | 7 |
| Executed total | 41 | 37 | 4 | 7 authored separately |

Four failing assertions reproduce three defect IDs, without skips or cancellations.
The recorded HTTP suite made 458 requests, including 285 tree pages. It returned
335 HTTP 200, 38 HTTP 400, 34 HTTP 404, 50 HTTP 405 and one HTTP 414.
All five JavaScript files passed Node syntax checking; no reviewed implementation
hash changed and no new write was outside A5 ownership. A preliminary run exposed
three QA-harness errors (Fetch TRACE/Host handling and row-canary scope); those
were corrected before the recorded run and are not product defects. The final
runner uses a 30-second per-test timeout and records progress to avoid a silent wait.

## Reviewed identity and scope

- Worktree branch: codex/site-functions-20261015-181420-c415-a5.
- HEAD: d7b6dc1e4d50b87a88cca036a6025352ecc0ccbe.
- The worktree already contained integration changes at audit start. HEAD alone
  does not identify the tested working copy. See [baseline](../dev/a5/baseline.json)
  for the initial status and SHA256 of 55 implementation/source-contract files.
- Writes are limited to quality/security/a5, tests/security, docs/security-review
  and docs/dev/a5. No implementation, source, credentials, DB, HEAD/index/branch or other
  worker files were changed. Git status gained only A5-owned files. No commit/push/PR/merge/deploy/container command ran.
- The actual target is http://127.0.0.1:8000. The three live integrated CSS/JS
  assets were compared with the reviewed files; hashes are in live-observations.json.

## Coordinator issue A5-001 — incomplete edition consistency validation

**Synthetic reproduction; medium integrity/robustness priority. No live drift found.**

Location: apps/reference/static/reference/django-api.mjs, verifyEdition (line 64).

The adapter checks edition ID, edition key and archive/input hashes, but accepts
changed title, publisher, heading_count, root_count, max_depth and every work
attribution field in subsequent page envelopes. The test changes each of these
nine fields while retaining hashes/key/ID; catalog() still resolves. Cached
attribution can therefore conceal an inconsistent server response. The current
live responses agree; this is not evidence of source corruption or an auth bypass.

Coordinator action: retain a validated immutable source projection and compare all
identity/attribution/count fields on every page/detail response. Reject mismatches
with INVALID_PAYLOAD. Keep the existing hash/key checks. The independent regression
is "SYNTHETIC ADAPTER A5-001" in adapter.test.mjs.

## Coordinator issue A5-002 — incomplete root and breadcrumb validation

**Two synthetic reproductions; medium integrity/robustness priority. Live tree is valid.**

Location: django-api.mjs, project/page/catalog (lines 68, 85, 110) and node
breadcrumb validation (line 132).

1. A roots response containing a depth-two child with non-null parent is accepted
   as the catalog's sole root when the advertised root_count is one.
2. A node and final breadcrumb marked depth five are accepted with only one
   depth-one parent. The parent ID chain links, but declared depth and path do not.

Coordinator action: require root parent_id=null and depth=1; verify unique root IDs;
require breadcrumb[i].depth=i+1 and node.depth=breadcrumb length; compare the final
breadcrumb projection with the selected node. Preserve the maximum depth of five.
Two ordinary failing tests named A5-002 provide minimal reproduction cases.

## Coordinator issue A5-003 — query-field limit escapes JSON error handling

**Actual HTTP reproduction; low API-contract priority. Request is safely rejected.**

Location: config/settings/base.py:57 (16 fields), apps/reference/views.py:14
(query parsing) and :41 (api_guard catches InvalidQuery, not TooManyFieldsSent).

Send GET /api/v1/fiqh/books with a0=1 through a16=1 (17 short query fields).
Actual: HTTP 400, Content-Type text/html; charset=utf-8, English "Bad Request" page.
Expected: generic 400 application/json with the catalog marker and invalid_query,
consistent with ordinary invalid/duplicate/unknown-parameter responses.
CSP/no-store/nosniff remain present; no exception details or sensitive data leaked.

Coordinator action: normalize Django's TooManyFieldsSent for API paths to the
existing generic JSON 400 envelope. Retain the field limit; do not expose exception
text or broaden arbitrary exception catching. The live A5-003 test stays failing.

## Source integrity and public-scope observations

The existing site represents exactly one work: shamela/622, كشاف القناع عن متن
الإقناع, Ministry of Justice edition, edition key 622-moj-owner-r1-20261011.
Actual live traversal covered 11,397 headings / 32 roots / maximum depth 5 and
validated original source IDs, parent chains, unique order, sibling ordering,
child counts, printed part/page and source page IDs. No fatwa/private/extra fields
were present in the public heading projection. Reconstructing the complete mapped
snapshot produced the pinned digest below, excluding injected or invented records
relative to that repository contract.

- Archive attribution: FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip.
- Archive pin: 82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce.
- Input member: FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl.
- Input pin: 37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14.
- Reconstructed mapped digest: b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7.

A5 did not open or rehash the original ZIP/member. This comparison proves agreement
with the repository's pinned mapped contract, not independent upstream authenticity
or provenance/rights acceptance. No direct SQL/ORM database test was run by A5.

Public IDs 25 and 622-25 are intentional source identifiers; the heading serializer
uses source_row_id, not the heading's internal primary key. The edition ID in the
inventory remains a documented selection key. No internal filenames, ingest checksum,
normalized title, requester, account, ruling body or arbitrary model fields appeared.

The edition selector is currently present. Automatic selection without editionId
also retains edition_key, work identity, archive/input hashes, printed references
and source IDs in the tested adapter. Models additionally retain the logical input
basename and ingest checksum. Removing a public selector need not erase those
fields; it must not flatten or replace source provenance. The live Arabic scope
note explicitly says one source index, not a global fatwa taxonomy or approved fatwas.

**Static integrity concern requiring DB-owner verification:** migration 0002 blocks
UPDATE/DELETE, but its INSERT trigger only checks parent edition/depth. The declared
schema does not seal a completed edition against appending a new otherwise valid
root/heading; stored edition counts/checksum would then describe the older snapshot.
Effective DB INSERT grants were not inspected. The importer detects an incomplete
or changed edition on a later comparison, and the current live digest is correct.
Have the DB owner test post-import append rejection in a disposable test database
and, if INSERT remains possible, enforce a completed-snapshot boundary or separate
read-only serving privileges. No INSERT/UPDATE/DELETE or rollback experiment was
performed in this audit. This concern is source review, not a reproduced DB defect.

## Evidence categories and limits

- Actual HTTP: public GET/HEAD, denied unsafe verbs (including TRACE/OPTIONS),
  private/auth/fatwa/intake/AI/delivery denial, origin/CSRF-style denial, SQL-like
  and wildcard input, XSS query reflection, error/content-type bounds, source-ID
  scope, complete source mapping, immutable public metadata, static asset allowlist,
  CSP/no-store/CORS/cookies, SSR fallback, Arabic/RTL/label/skip/live-region markup.
- Cross-origin POST is rejected by global method enforcement before CSRF dispatch;
  this does not claim an independently exercised CSRF-token mechanism.
- Malicious original Arabic source titles: adapter projection and source textContent
  checks executed. The seven isolated Django tests include actual SSR template
  escaping of such a source title, but remain NOT_RUN because Python is unavailable.
  Live reflected query escaping is tested separately and passes.
- Browser/mobile/keyboard/screen-reader execution: NOT_RUN. Connected inventory was
  empty; opening iab returned "Browser is not available: iab". HTML checks are not
  browser acceptance. Real 503 behavior under a DB outage was not induced; isolated
  Python error tests were authored without stopping the existing service.
- Direct PostgreSQL trigger/grant/constraint tests: NOT_RUN. All live evidence is
  actual HTTP to an ORM-backed site; synthetic tests are labelled separately.
- Python attempt: py -3.13 -B manage.py test tests/security --settings=config.settings.test
  exited 112: "No installed Python found!" See django-not-run.json.

Reproduction: node quality/security/a5/run.mjs. It intentionally exits 1 while the
four regression assertions for A5-001/A5-002/A5-003 remain failing. See
[results](../dev/a5/results.json), [HTTP TAP](../dev/a5/http.tap),
[adapter TAP](../dev/a5/adapter.tap), [static TAP](../dev/a5/static.tap) and
[live observations](../dev/a5/live-observations.json).
