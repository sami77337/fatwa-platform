# Wave7 E2 producer contract

Base: 34355f5173667c6167351cf379ad56957d7f35f3; branch codex/20261017-wave7-e2.
No shared models/migrations/guards/settings/routes changes; no PR58 metadata edits.

Public service in `apps.intake_workflow.review`:

```python
transition_review(item_id, *, operation_id, action: str, expected_status: str,
                  reason: str, synthetic_fixtures_only: bool = False,
                  using: str = 'default') -> ReviewTransitionResult
load_review_worklist(*, batch_id=None, row_id=None, q: str = '', mode: str = 'normalized', intake_status: str = '',
                     review_status: str = '', page: int = 1, page_size: int = 20,
                     synthetic_fixtures_only: bool = False,
                     using: str = 'default') -> ReviewWorklist
```

UUID inputs are UUID objects or canonical UUID strings; no external-ID selection.
`ReviewTransitionResult`: item_id, event_id, operation_id, from_status, to_status,
replayed. Expected status is required optimistic concurrency input. An exact replay
matches operation UUID, action, expected/from status and exact reason, and returns
its original event even after later transitions; conflicting reuse returns
`ReviewConflict` (code REVIEW_CONFLICT, status_code 409). Not-found is
`ReviewNotFound` (404); invalid input/illegal action uses ContractError (400).
There is exactly one synthetic_atomic write unit; row lock precedes event lookup
and status/event update. No answer, approval, publishing or HTTP writes.

Read DTO: ReviewWorklist with batches, batch_id, rows, row, total_count,
matched_count, page, page_count, page_size, q, mode, intake_status, review_status.
Stored row: id, batch_id, row_ordinal, external_id, question, original_row,
source_byte_start/end, intake_status, review_status, prepared_clip_url, references,
events, events_truncated. Source fields come from the approved parser/source slices,
never default float JSON rewriting. References expose original_pointer and exact
source offsets, reference_status and stored citation_text (only for VERIFIED).
Latest 100 events are shown on detail with an explicit truncation marker; lists
load no event histories. Batch selector lists latest 100, retaining a selected old
batch. Explicit UUID deep links remain valid across process restarts.

CLI: `python manage.py wave7_review --settings=config.settings.wave7_development transition --item UUID --operation UUID --action
start_review --expected-status UNREVIEWED --reason 'Synthetic review reason'
--synthetic-fixtures-only`.
No command-level outer atomic; fixed/sanitized result/error codes only.

E5 proposed shared integration patch (E2 does not edit shared settings/routes):
- In separate Wave7 settings only, WAVE7_READS_ENABLED is exactly
  os.environ.get('FATWA_WAVE7_SYNTHETIC_READS') == '1'. The old
  WAVE7_REVIEW_READ_ENABLED may alias that boolean for compatibility; it is not
  an independent gate or environment variable. E2 now uses E4's exact flag gate.
- One separate config.wave7_urls registers E2's named route
  path('dev/editorial-preview/persisted', editorial_views.persisted_review,
  name='wave7_editorial_review') before the legacy generic editorial route,
  E4's three actual workflow APIs, then unchanged config.urls patterns.
- Select that URLconf only in separate Wave7 settings with reads enabled.
- Existing ownership/schema/write-enablement guards remain mandatory. E4's read
  guard opens no transaction and grants no write permit. Writes and CLI stay
  unchanged. No root settings/URLs/models/migrations/guards are changed here.

Persisted GET query: batch UUID, row UUID, q <=80 chars and <=10 tokens,
mode exact/literal/normalized (default normalized), intake_status, review_status,
page (1..10000), page_size (1..50), with offset (page-1)*page_size <=20000.
Unknown/duplicate params and invalid bounds fail400 before SQL. Row requires
batch. Every detail/page/return link preserves batch, mode and filters. Legacy
Wave6 behavior remains unchanged. The three modes search original questions,
using actual E4 semantics; external IDs remain display metadata, not search aliases.

Actual dependency: apps.reference.services.workflow_items supplies exact filtered
page IDs/order/total; workflow_item supplies detail metadata, original SourceSlice,
current reference state/citation and reference SourceSlices. E2 keeps the latest100
batch selector plus selected older batch, exact selected-payload SHA validation,
bounded list source/reference projection and bounded event history. No per-list-row
workflow_item call or JSON source decoding. E4's declared 400/404/503 failures
propagate as fixed safe no-store responses; no missing-service/empty-PASS fallback.
The internal E4 dependency and completed local composition evidence are recorded
in E4_ADAPTATION_PLAN.md and E4_ADAPTER_EVIDENCE.md.

Required no-DB label: tests.editorial_demo.test_wave7_review_off.
Required DB-only labels (TransactionTestCase, wave7_test settings, PG17/18):
- tests.editorial_demo.test_wave7_review_db
- tests.editorial_demo.test_wave7_read_db
- tests.editorial_demo.test_wave7_e4_adapter_db (8 methods; actual E4 required)
Never send the DB labels to C6/D6's port-1 runner. Actual counts follow implementation.
