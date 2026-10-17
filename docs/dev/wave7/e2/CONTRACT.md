# Wave7 E2 producer contract

Base: 34355f5173667c6167351cf379ad56957d7f35f3; branch codex/20261017-wave7-e2.
No shared models/migrations/guards/settings/routes changes; no PR58 metadata edits.

Public service in `apps.intake_workflow.review`:

```python
transition_review(item_id, *, operation_id, action: str, expected_status: str,
                  reason: str, synthetic_fixtures_only: bool = False,
                  using: str = 'default') -> ReviewTransitionResult
load_review_worklist(*, batch_id=None, row_id=None, q: str = '', intake_status: str = '',
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
matched_count, page, page_count, page_size, q, intake_status, review_status.
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

E5 proposed shared integration patch (do not apply to public/base settings):
- Separate Wave7 settings flag `WAVE7_REVIEW_READ_ENABLED =
  os.environ.get('FATWA_WAVE7_REVIEW_READ') == '1'` (default off).
- Separate Wave7-only URLconf first registers
  `path('dev/editorial-preview/persisted', editorial_views.persisted_review,
  name='wave7_editorial_review')`, then includes the existing config.urls.
  The new route must precede the legacy generic editorial `<str:ident>` route.
- Set ROOT_URLCONF to that URLconf only in separate Wave7 settings.
- Existing ownership/write flags remain mandatory; reads use require_owned_database
  before ORM queries, writes use the unchanged synthetic_atomic guard.

Persisted GET query: batch UUID, row UUID, q <=80 chars, intake_status,
review_status, page (1..10000), page_size (1..50); reject unknown/duplicate params.
Row requires batch. Filter/page/batch remain in all detail/return links. New view
is require_safe + loopback + feature guard; the original Wave6 views are unchanged.
Template reuses pipeline.html with a persisted-only context branch. E4 may use the
public read DTO for its own read interface; no duplicate model/route ownership.

Required no-DB label: tests.editorial_demo.test_wave7_review_off.
Required DB-only labels (TransactionTestCase, wave7_test settings, PG17/18):
- tests.editorial_demo.test_wave7_review_db
- tests.editorial_demo.test_wave7_read_db
Never send the DB labels to C6/D6's port-1 runner. Actual counts follow implementation.
