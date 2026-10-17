# Wave7 E4 read contract for E2/E5/E6

Foundation: `34355f5173667c6167351cf379ad56957d7f35f3` (root supplied independent acceptance; old pending wording/PR58 metadata untouched). Leadership full v1.0/continuation/final clarifications received during execution and reconciled: source scope/ref ownership/owned nonempty DB/CLI-only writes already agree with the frozen code. Approved lossless storage overrides early JSON field types. No shared schema or guard change requested.

## Actual service signatures (apps.reference.services)

```python
workflow_batches(*, text='', mode='normalized', intake_status=None,
                 review_status=None, page=Page(20),
                 synthetic_fixtures_only=False, using='default') -> WorkflowPage
workflow_items(*, batch_id=None, text='', mode='normalized', intake_status=None,
               review_status=None, page=Page(20),
               synthetic_fixtures_only=False, using='default') -> WorkflowPage
workflow_item(item_id, *, batch_id=None, synthetic_fixtures_only=False,
              using='default') -> WorkflowItemDetail
```

UUID inputs accept UUID objects or canonical 36-character UUID strings, never external IDs or numeric coercion. Output UUIDs are canonical strings. Calls must explicitly acknowledge synthetic fixtures. Status values are frozen uppercase IntakeStatus/ReviewStatus strings or None. Reference verification remains separate from intake readiness.

`WorkflowPage`: frozen `items` tuple, `total`, `limit`, `offset`, `next_offset`; `.as_dict()` is an explicit JSON-safe projection. Page is existing `apps.reference.query.Page`, limits 1..100 and offsets 0..20,000. Fixed sort: batches `(created_at,id)`; items `(batch.created_at,batch_id,row_ordinal,id)`. There is no caller-controlled sort field.

`WorkflowBatchRead`: `id`, `idempotency_key`, `created_at`, `item_count` (all retained rows, not just matches).
`WorkflowItemRead`: `id`, `batch_id`, `row_ordinal`, nullable `external_id`, nullable EXACT `question_original`, `intake_status`, `review_status`, `reference_count`, `verified_reference_count`. Invalid/null rows remain visible when browsing, duplicate external IDs are not identity. Selecting the wrong batch for an item gives not-found.
`WorkflowItemDetail`: `item` summary, `source: SourceSlice`, `references: tuple[WorkflowReferenceRead,...]`, `prepared_clip_url: str | None`, `validation_results` (derived metadata).
`WorkflowReferenceRead`: `id`, `reference_ordinal`, `source: SourceSlice`, stored `reference_status`, `citation_text: str | None`, `verification_results` (derived metadata). Only a stored VERIFIED ref with the complete frozen identity can return a citation. Missing/UNVERIFIED/MISMATCHED refs never invent one. All strings remain plain text for E2's normal template escaping; never mark source/citation safe. Media strings are metadata only; E2 must keep its existing invalid/missing-media display policy and never fetch/play media.

No default float parsing or numerical remapping of source values. Detail uses the approved batch parser once and verifies persisted item/ref SourceSlice text and byte bounds at actual ordinals; original lexical numbers stay inside source text. JSON returns these tokens as exact source strings, not decoded/re-encoded numerics. It never infers archive/source acceptance from stored pins.

## Search and read gating

Blank/whitespace text browses all scoped rows and applies selected statuses/batch, including blocked rows. Nonblank marks/tatweel normalized to empty matches nothing. Exact mode compares the whole unchanged question. Literal mode ANDs literal tokens (bound/escaped ORM values). Normalized mode reuses existing `normalize_title()` exactly (NFKC, Arabic marks, whitespace and casefold); originals are not changed.

There is no normalized column in the accepted schema. Normalized scanning is explicitly capped at 1,000 candidate questions and 1,000,000 total UTF-8 question bytes after batch/status filtering, streamed with one-row chunks; excess raises `WorkflowSearchScopeRequired`, never partial results. Select a smaller batch/status scope. This is a read-work bound, not an input-schema rejection or a new source policy. Literal/exact and blank browse use bounded ORM pages directly. Summary queries defer full payload/source tokens; detail loads one bounded batch and at most 100 references.

Reads are default off: `WAVE7_READS_ENABLED is True`, `FATWA_WAVE7_SYNTHETIC_READS=1`, and the separate workflow app must be registered. Then the existing shared `require_synthetic_write()` validates the fixed scope/configuration, PROD=0, writes opt-in, role, loopback, exact names/actual ownership and current schema. Despite its name this call only performs validation SELECTs; reads do not open atomic(), set a write tag, initialize a DB or seed fixtures. No duplicated guard logic or transaction wrapper. E2 calls reads AFTER any review write unit commits, never from inside that unit.

Errors: `WorkflowReadsDisabled` (404), `WorkflowItemNotFound` (404), `InvalidQuery` (400), `WorkflowSearchScopeRequired` (400, shrink scope), `WorkflowReadUnavailable` (503, redacted). Services never repair/fallback to a fixture on failure.

## Actual E4 views/context (apps.reference.views)

- `api_workflow_batches(request)`: GET/HEAD; q/mode/intake_status/review_status/limit/offset.
- `api_workflow_items(request)`: same plus optional batch UUID.
- `api_workflow_item(request, ident)`: GET/HEAD; optional batch UUID only.
- `workflow_read_context(request, *, item_id=None) -> dict`: shared E2 SSR list/detail data, exact same list query parser and service DTOs. Checks existing loopback host AND peer gate and feature flag. No new template/UI.

Context keys: `workflow_page`, `workflow_item`, `workflow_query`, `workflow_mode`, `workflow_batch`, `workflow_intake_status`, `workflow_review_status`, `workflow_limit`, `workflow_offset`, `workflow_filter_query`, `workflow_return_query`, `workflow_previous_query`, `workflow_next_query`. Query strings preserve exact text and validated list filters/paging. E2 combines them only with its named route. Root supplied E2's actual new single persisted screen `/dev/editorial-preview/persisted` (`views.persisted_review`, name `wave7_editorial_review`), separately opt-in; legacy `/dev/editorial-preview/pipeline` remains untouched by E4. On detail, filters/offset describe the return list; item selection is UUID+optional batch. No arbitrary return URL.

JSON kind is `WAVE7_SYNTHETIC_WORKFLOW`; errors are fixed codes `invalid_query`, `not_found`, `workflow_unavailable`, `search_scope_required`, `method_not_allowed`. Unknown/duplicate/excessive params fail. No HTTP writes, auth/session/admin changes, or public-catalog contract changes. New catalog.js code is unnecessary: E2's single native SSR worklist owns filter/page/detail/history/keyboard UI; all existing catalog async regressions remain unchanged and run.

## E5-only minimal integration patch (NOT applied here)

Only in `config/settings/wave7_development.py` (inherited by wave7_test):

```python
WAVE7_READS_ENABLED = os.environ.get('FATWA_WAVE7_SYNTHETIC_READS') == '1'
if WAVE7_READS_ENABLED:
    ROOT_URLCONF = 'config.wave7_urls'
```

New E5-owned `config/wave7_urls.py` (combine E2's actual UI hooks here if needed):

```python
from django.conf import settings
from django.urls import path
from config.urls import urlpatterns as legacy
from apps.reference import views

urlpatterns = list(legacy)
if getattr(settings, 'WAVE7_READS_ENABLED', False) is True:
    urlpatterns += [
        path('dev/wave7/api/batches', views.api_workflow_batches, name='wave7_api_batches'),
        path('dev/wave7/api/items', views.api_workflow_items, name='wave7_api_items'),
        path('dev/wave7/api/items/<str:ident>', views.api_workflow_item, name='wave7_api_item'),
    ]
```

`str:ident` deliberately reaches the JSON UUID validator for malformed UUIDs. No base/public URLConf/middleware change is proposed. These endpoints exist only in E4's TEST-ONLY URLConf until E5 applies integration. This documentation is not a claim that shared routes/settings are wired.

## Exact test labels and E6 handoff

- No DB/default off: `tests.integration.api.test_wave7_workflow_reads`.
- Real PG ONLY: `tests.integration.ui.wave7_workflow_reads_db` (TransactionTestCase, filename deliberately not `test_*.py` so legacy discovery never imports an absent workflow app). Explicitly wire this label once in a separate Wave7 PG17/18 job, never port-1 C6/D6.
- Existing Wave6 Node/API/default-off suites remain required. No source gate acceptance inferred.

PR59 E6 `INTEGRATION_HANDOFF.md` at `2966b9937262c446b70607c9127793e884ef150c` was read. E6 can call these service/JSON hooks with persisted UUIDs from E1. Native controls/event history selectors remain E2-owned; E4 does not fabricate their arrival. Root supplied E2's loader `load_review_worklist(*, batch_id=None, row_id=None, q='', intake_status='', review_status='', page=1, page_size=20, synthetic_fixtures_only=False, using='default')`. E2 can map q→text, row_id→item_id, empty statuses→None, and page/page_size→Page(page_size,(page-1)*page_size) into these services; its event history remains E2 owned. Root/E2 must apply that E2-owned adapter if the independently implemented loader is not yet consuming E4. E5 wires its `WAVE7_REVIEW_READ_ENABLED` screen flag alongside the E4 shared read gate and places the persisted GET path before the legacy generic `<str:ident>` route. E2 supplies native controls/event/citation selectors to root/E6; E4 does not duplicate the UI. Actual combined UI/browser/service-command restart journeys remain NOT_RUN until assembly. No E6/other-lane files edited.
