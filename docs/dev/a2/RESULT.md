# A2 bounded catalog API handoff

Development changes only. **NOT_DEPLOYED / GATES_HOLD**. No commits, pushes, PRs,
source-site changes, imports, migrations, or persistent database writes were performed.

Base commit: `d7b6dc1e4d50b87a88cca036a6025352ecc0ccbe`. The starting working tree
was the owner's integrated **dirty snapshot**. In particular, services.py and views.py
already contained integration changes; those changes were retained. File fingerprints
before and after A2 are in [verification.json](verification.json).

## Implemented within A2 ownership

- Roots and direct children have explicit ordering by position, source_order and
  source_row_id. Anchored paging uses that same ordering and counts preceding rows;
  it does not assume source positions are contiguous. Pages remain limited to 100
  rows and offsets to 20,000. Continuations cannot advertise an inadmissible offset.
- Empty or normalization-empty search now validates a supplied root. Missing roots
  return 404 and non-root scope returns 400 even if q is empty. Previously both
  could be silently ignored by the empty-search return.
- Root scope uses at most four parent joins. Each ancestor must belong to the selected
  edition, and internal ancestor comparisons use database primary keys. Public IDs
  remain original source row IDs; different editions may reuse those source IDs.
- Direct-child counts are restricted to the same edition. Breadcrumbs retain the
  selected heading, cover depths one through five, read at most four additional
  parents, and reject wrong editions, wrong parent PKs, invalid depths or missing
  parents with a redacted 503.
- Exactly one edition is still resolved automatically for API and HTML requests.
  Ambiguous API requests remain 400. HTML without a selected edition may show the
  root chooser, but ambiguous search, node and paged content requests now return 400.
- Syntactically invalid page, root and anchor parameters are rejected before edition
  lookup. APIs and HTML views themselves enforce GET/HEAD, in addition to the existing
  global read-only middleware. Health/readiness also validate their empty parameter
  contract; database/schema/hierarchy errors remain redacted.
- Basic HTML node and branch routes now accept `anchor=SOURCE_ROW_ID` with no offset,
  allowing direct result reveal without JavaScript. Previous/next links use the
  effective anchored page, rather than the original zero request offset.
- Original Arabic titles, printed part strings (including المقدمة), printed pages,
  source page IDs and source IDs retain their existing explicit public projection.
  No models, stored titles, schema or importer were changed.

## Actual verification and limits

| Check | Actual result | What it proves |
| --- | --- | --- |
| Ruff check on the 6 A2 Python files | PASS | Parsing/lint checks only |
| Ruff format check on the same files | PASS | Formatting only |
| git diff --check on the 3 owned application files | PASS | No diff whitespace errors |
| Node syntax check of live_read.test.mjs | PASS | JavaScript syntax |
| Existing tests/integration/django-api.test.mjs | 11 PASS | Existing frontend adapter with mocked HTTP |
| New opt-in live read suite, http://127.0.0.1:8000 | 5 PASS, 1 SKIP | GET/HEAD behavior of the **untouched existing server**, not this A2 candidate |
| New isolated Django ORM suite | NOT_RUN | Python launcher exits 103 because its base Python313 executable is access denied |
| Candidate HTTP and PostgreSQL execution | NOT_RUN | A2 was not started and no disposable database was created |

The new ORM tests use real Django QuerySets, PostgreSQL SQL compilation and model
materialization with canned synthetic DB-API cursor rows. They do not replace the
QuerySet implementation. The standalone runner supplies synthetic settings, blocks
`get_new_connection`, and uses SimpleTestCase; it never invokes Django's database
creation, migrations, importers or source fixtures. **These tests are not PostgreSQL
acceptance even when run successfully. They have not run in this session.**

The current source server still reproduces both changed behaviors:

- `GET /api/v1/fiqh/search?q=&root=999999` returns 200; candidate expectation is 404.
- `GET /fiqh/nodes/2214?basic=1&limit=20&anchor=2255` returns 400; candidate expectation is 200.

The candidate-only live case is intentionally skipped unless explicitly enabled.
No current-server result is presented as verification of candidate fixes.

## Source evidence from read-only access

The actual original archive was read and hashed; its JSONL was streamed into memory
with 7-Zip's stdout mode, without extracting source files to disk or reimporting:

- Archive: FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip
- Archive SHA256: `82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce`
- Input member: FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl
- Input SHA256: `37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14`
- Actual input: 11,397 rows, 32 roots, maximum depth five.
- All 32 live root projections matched the original source for IDs, original title,
  parent, depth, sibling position, child count and printed/source references.
- Live shallow samples: IDs 1 and 2. Both depth-five source headings were checked:
  8668 follows 8550 / 8551 / 8665 / 8667 / 8668; 9709 follows
  9693 / 9694 / 9700 / 9708 / 9709.
- Live anchored parent 2214, child 2255, limit 20 returned offset 40. Each edge of
  both five-level paths was also revealed with a bounded anchored child request.
- Archive SHA256 was unchanged at the end of the checks. This is read-only source
  and current-server evidence, not acceptance of all 11,397 persisted candidate rows.

## A1/coordinator integration notes

No A1 file was edited. The existing JSON envelopes, kind marker, source hashes,
heading fields, node ancestors and API parameter names are preserved.

1. The existing templates still render edition controls when only one source exists.
   A2 serves the data without an edition parameter and adds HTML context flags
   `single_source` and `edition_selection_required`. A1 should hide the unnecessary
   chooser when `single_source` is true while preserving search and source identity
   in links or hidden values. This visual change requires A1 ownership.
2. The basic node/branch anchor addition needs no frontend change. The interactive
   adapter already uses the API's anchored children and node ancestors for reveal.
3. Root scope remains an API operation. The existing SSR form/paging templates do
   not retain root scope, so A2 did not add a misleading partial HTML root filter.
4. The existing adapter caps totals at 20,000, uses JavaScript safe integer IDs and
   searches only the first 100 inventory entries for an explicitly selected edition.
   The actual source fits those limits. Future larger inventories or source IDs
   require a coordinated adapter/API contract change; no silent fallback was added.
5. Multi-edition behavior and malformed hierarchy cases have synthetic isolated
   regression tests but were not exercised on a real multi-edition PostgreSQL DB.

## Rerun without touching the persistent database

With an accessible Python 3.13 and the repository's pinned dependencies:

~~~powershell
python -B tests/integration/api/run_isolated.py
ruff check apps/reference/services.py apps/reference/views.py apps/reference/query.py tests/integration/api --no-cache
ruff format apps/reference/services.py apps/reference/views.py apps/reference/query.py tests/integration/api --check --no-cache
node --test tests/integration/django-api.test.mjs
~~~

Against an already running local catalog, the following makes GET/HEAD requests only:

~~~powershell
$env:FATWA_A2_LIVE_ORIGIN = 'http://127.0.0.1:8000'
node --test tests/integration/api/live_read.test.mjs
~~~

Only after the coordinator starts this A2 candidate independently, enable its added
expectations with `$env:FATWA_A2_EXPECT_PATCH = '1'` and rerun the same live suite.
Do not run the source-site launcher, container_workflow.py, migrations or importers
as part of these checks.

Django behavior was reviewed against the official 5.2 references for
[QuerySets](https://docs.djangoproject.com/en/5.2/ref/models/querysets/),
[aggregation](https://docs.djangoproject.com/en/5.2/topics/db/aggregation/) and
[safe-method decorators](https://docs.djangoproject.com/en/5.2/topics/http/decorators/).
