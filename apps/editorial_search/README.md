# Unified Arabic editorial search (FAST4)

Development-only, synthetic, read-only search at `/dev/editorial-search`.
Base: FAST3 PR #106, `a149b39bfd624e330762459a7c3e0b4febc7187b`.

With the pinned requirements installed on Python 3.13, reuse the existing
`python -m apps.editorial_queue` loopback launcher and open
`http://127.0.0.1:8014/dev/editorial-search`. This avoids database preflight for
these in-memory fixtures. The normal Django development server also serves
the route. No new settings, app registration or dependencies are required.

Implementation plan: reuse `build_queue_catalog()` for original cases, prepared
batches, validated revision history and reference diagnostics. Build ephemeral
search documents by question, draft revision, reference, record, batch and
technical status. Reuse `normalize_title()` on matching copies only. Preserve
source strings in results and escaped HTML, including CR/LF and combining marks.
Return 10 results per page, at most 200 results, with exact normalized field
matches first and deterministic source order within each relevance tier.
Explicitly report truncation. Link snapshots by revision number, not position;
intake diagnostics and batches have no invented revision identity.

Work sequence: (1) failing service/HTTP tests, (2) service and guarded RTL SSR,
(3) focused new and directly affected tests, (4) independent review, commit/push
and one draft PR to the FAST3 branch. The user explicitly requested immediate
implementation, an existing isolated worktree and focused verification.

Queries use all whitespace-separated normalized terms within a document (AND).
Normalization handles Arabic marks/tatweel, alef variants, alef maqsura, Unicode
compatibility forms and Latin case using the existing reference normalizer.
Empty or mark-only queries return no results. Query limit: 80 code points.
Unknown/repeated parameters, controls, unsupported source types, unknown batches,
and noncanonical/out-of-range pages fail safely. No database or external index.

References are the available fixture identities and diagnostic evidence only,
not a search of protected books or an assertion of scholarly verification.
Prepared source text may be the existing adapter's serialized fields rather
than original file bytes; fixture labels, payload and row digests remain visible.
Rejected rows and malformed batches never acquire fabricated drafts/revisions.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED. No publication, scholarly approval, privileged action, migrations,
private records, source-asset changes, or external search services.

Focused validation (Python 3.13.17 / Django 5.2.18):

```powershell
python manage.py test tests.editorial_search.test_services tests.editorial_search.test_views --settings=config.settings.test --noinput
python manage.py test tests.editorial_queue.test_services tests.editorial_queue.test_views tests.editorial_queue.test_cross_batch tests.editorial_workbench.test_services tests.editorial_workbench.test_views tests.editorial_workbench.test_batches --settings=config.settings.test --noinput
python manage.py check --settings=config.settings.development
python -m ruff check apps/editorial_search tests/editorial_search
python -m ruff format --check apps/editorial_search tests/editorial_search
git diff --check
```

Tests use `SimpleTestCase`, which forbids database access. These checks do not
claim PostgreSQL integration or owner ZIP acceptance. Fixtures are the existing
`fixtures.synthetic_payload()`, `REVISION_HISTORY_RECORD` and
`batch_fixtures.synthetic_inputs()`; their input SHA-256 manifest is maintained
in [the reused queue documentation](../editorial_queue/README.md).
Source offsets remain available through each exact case link. No source assets
are modified. Revert this feature commit to remove the module and route.

2026-10-25 results: 18 search tests and 66 directly affected queue/workbench tests
passed; Django check, Ruff lint/format and whitespace checks passed. Independent
final review found no critical or important findings and checked all 119 search
documents / 48 unique target links (HTTP 200, valid anchors, exact revisions).
Chrome smoke check submitted `منقح` with the draft filter, showed revisions
2/4/7/9/11, and opened revision 2 in the existing workbench. This is a focused
desktop check, not a full accessibility or mobile acceptance claim.

## FAST7B exact-match relevance (2026-10-26)

Base: FAST6 PR #121, `667fd70217d794169c23569ce2df0396dcd27f7c`.
Scope: `apps/editorial_search/` and `tests/editorial_search/` only.

Reproduced on the fixed synthetic catalog: `سؤال اصطناعي` placed the exact
question `intake-3` fourth; reference query `verified` showed `UNVERIFIED`
substring matches before exact technical statuses. Exact normalized whole-field
matches now come first. All existing AND substring matches remain eligible;
equal relevance retains original catalog/document order, including gapped
revision numbers. This is text relevance, never scholarly verification.

Ranking runs before pagination and the 200-result cap. A bounded selection
retains at most 201 candidates while scanning all eligible documents, so a late
exact hit can displace an earlier partial hit; the extra candidate detects
truncation. Matching still uses ephemeral normalized copies, with no changes
to source bytes, record IDs, reference evidence, query limits or target URLs.
No stemming, fuzzy matching, external index, new dependencies or migrations.

Validation uses the existing synthetic fixture identities documented above,
plus explicitly constructed in-memory ranking/cap/Unicode cases in search tests.
Four new regressions failed before implementation (question, draft, technical
reference ordering and a late exact hit beyond the cap). Exact question and
reference links and gapped draft links are followed through the real local HTTP
views; negative queries must not combine separate reference occurrences.
Only focused search and directly affected navigation tests are rerun. No
PostgreSQL, owner-source acceptance or new browser acceptance is claimed.
Rollback is code-only by reverting this change. Official gates remain unchanged.

Measured result: Python 3.13.15 / Django 5.2.18, 40 tests passed (27 search and
13 directly affected workbench-view/navigation tests). Scoped Ruff lint/format
and whitespace checks passed. One independent final read-only review found no
issues, reran the 27 search tests and checked 199/200/201-match boundaries.

```powershell
python -B manage.py test tests.editorial_search.test_services tests.editorial_search.test_views tests.editorial_workbench.test_views tests.integration.test_fast4 tests.integration.test_fast5.Fast5IntegrationTests.test_shared_navigation_connects_fast5_and_existing_fast4 --settings=config.settings.test --noinput
```
