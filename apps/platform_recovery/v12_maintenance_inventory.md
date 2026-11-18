# V12 P0 maintenance wrapper inventory

Pinned inspection base: `5ecc46fbb252adc06e0e0a1cbeb129eb7fe00c64` (#230).

Method: parsed function bodies/decorators/calls across application Python files, excluding
tests, migrations and fixture modules; manually followed canonical case/queue/attachment,
HTTP/session, storage conversion/GC and administration call chains. The table is an
inventory of existing entry wrappers, not proof that arbitrary Python/ORM/SQL cannot write.
Line numbers refer to the inspected base and may move during integration.

## Existing service wrappers

`S` = `mutation_service`; `C` = outer `mutation_context` on a contextmanager.
Read projections are intentionally included where they lock, create an audit head,
or share a guarded service path. These wrappers hold native commits; they add no new atomic.

| Module | Guarded entrypoints (base line) |
|---|---|
| `apps/answer_media/services.py` | `save_multipart_answer` S:158, `release_private` S:314, `staff_snapshot` S:481, `requester_snapshot` S:521, `requester_read` S:534, `staff_read` S:547 |
| `apps/case_attachments/services.py` | `upload` S:33, `requester_list` S:133, `requester_read` S:140, `staff_list` S:147, `staff_read` S:154 |
| `apps/case_attachments/storage_bindings.py` | `binding_locks` C:65, `migrate_original` S:127 |
| `apps/case_citations/services.py` | `search_sources` S:106, `_search_sources_for_rights_review` S:129, `read_source` S:213, `save_cited_answer` S:224, `read_citations` S:381, `suggest_sources` S:397, `read_citation_history` S:416 |
| `apps/casework/delivery.py` | `prepare_case_delivery` S:160, `stage_case_delivery` S:192, `reserve_case_delivery` S:266, `resolve_case_delivery_text` S:297, `record_case_provider_event` S:326, `requester_delivery_status` S:389 |
| `apps/casework/services.py` | `intake_case` S:357, `read_case` S:447, `list_cases` S:453, `save_answer` S:474, `request_clarification` S:511, `record_decision` S:537, `requester_status` S:630, `add_followup` S:636, `rotate_access` S:667, `revoke_access` S:679 |
| `apps/composite_delivery/desk.py` | `read_delivery_desk` S:231, `apply_desk_action` S:297 |
| `apps/composite_delivery/services.py` | `prepare_composite_delivery` S:169, `stage_composite_delivery` S:190, `reserve_composite_part` S:248, `resolve_composite_part` S:274, `record_composite_event` S:319, `composite_status` S:333, `reconcile_composite_timeouts` S:389 |
| `apps/delivery_queue/approval_adapter.py` | `commit_signed_approved_plan` S:109, `reserve_signed_plan` S:143, `prepare_text_return` S:178, `resolve_reserved_text` S:209 |
| `apps/delivery_queue/reporting.py` | `export_scoped_report` S:15 |
| `apps/delivery_queue/requester_tracking.py` | `provision_tracking_case` S:136, `rotate_tracking_token` S:159, `advance_tracking_case` S:179, `lookup_case_status` S:212 |
| `apps/delivery_queue/services.py` | `synthetic_queue_atomic` C:121, `verify_audit_chain` S:188, `commit_approved_plan` S:238, `claim_next` S:320, `record_receipt` S:363, `quarantine_expired_leases` S:441, `summarize_plan` S:486 |
| `apps/delivery_queue/signed_provider_receipts.py` | `record_signed_provider_event` S:200, `audit_provider_reported_delivery` S:315 |
| `apps/experimental_publication/services.py` | `create_edition` S:131, `act` S:183, `editorial_case` S:250, `desk` S:263, `correction_draft` S:386, `library` S:401 |
| `apps/intake_workflow/guards.py` | `initialize_synthetic_database` S:138, `synthetic_atomic` C:201 |
| `apps/intake_workflow/management/commands/migrate.py` | `handle` S:10 |
| `apps/knowledge_links/services.py` | `propose` S:226, `act` S:278, `browse` S:338, `desk` S:431, `open_material` S:487, `preview_material` S:500, `history` S:515 |
| `apps/library_preview/services.py` | `browse` S:253, `read` S:303, `read_reference` S:312 |
| `apps/mufti_review/services.py` | `submit_request` S:63, `record_decision` S:96, `review_history` S:136, `stage_reviewed_response` S:171, `reserve_reviewed_request` S:197 |
| `apps/pilot_workbench/services.py` | `read_workbench` S:84, `apply_action` S:119 |
| `apps/pilot_workbench/fixtures.py` | `setup_synthetic_fixture` S:205; explicit synthetic bootstrap, separately inspected |
| `apps/requester_access_review/recovery.py` | `recover_lost_access` S:94 |
| `apps/requester_access_review/services.py` | `requester_snapshot` S:82, `request_review` S:179, `staff_queue` S:195, `advance_review` S:221 |
| `apps/requester_portal/services.py` | `snapshot` S:49, `submit_reply` S:175 |
| `apps/research_workspace/services.py` | `search` S:237, `open_resource` S:439, `add_citation` S:500 |
| `apps/source_case_intake/desk_services.py` | `inbox` S:65, `detail` S:152, `timeline` S:221, `record_note` S:265, `resume` S:337 |
| `apps/source_case_intake/desk_simulator.py` | `simulate` S:22 |
| `apps/source_case_intake/services.py` | `capture` S:55, `process` S:164, `ingest` S:205, `review_queue` S:221, `resolve_review` S:231, `attach_fixture` S:305, `staff_origins` S:393, `staff_raw` S:413 |
| `apps/source_rights/services.py` | `register` S:178, `propose` S:222, `review` S:278, `correct_citation` S:377, `propose_relation` S:447, `act_on_relation` S:484, `desk` S:527 |
| `apps/team_updates/services.py` | `read_inbox` S:17, `mark_seen` S:43 |
| `apps/team_workspace/presentation.py` | `read_workspace_case` S:61 |
| `apps/transcript_case_links/services.py` | `preview` S:44, `attach` S:87, `read_links` S:151 |

## Composed boundaries inspected

| Boundary | Actual admission/lifetime |
|---|---|
| `casework.services._staff_case`, `_token_case` | Internal contexts; `_guard` reaches queue admission preflight. Public services/HTTP own the enclosing lease. These internal contexts are not new public entrypoints. |
| `casework.delivery_reconciliation.read_case_delivery_followup`, `quarantine_case_delivery` | `delivery._staff_case` → decorated `queue.synthetic_queue_atomic`, holding through full context exit. No independent queue added. |
| `intake_workflow.intake.import_intake`, `references.verify_batch_references`, `review.transition_review` | Decorated `guards.synthetic_atomic` surrounds the native transaction; pure parsing/planning remains read-only. |
| `reference.ingest.ingest_catalog` | Dry run is read-only; committed import explicitly enters `mutation_scope` before `transaction.atomic`. |
| `case_citations.composer.start/compose` and action views | Shared HTTP scope, then canonical case/source/answer service. Signed browser scratch data is not another database draft. |
| `private_media.filesystem.FileSystemStorage.__init__/put/restore` | `storage_scope(root)` before directory/lock/write operations, pinned private root. `get` is an immutable byte read. |
| `FileSystemStorage.collect_orphans` | `storage_scope(root, operation="GC")` encloses scan, reference callback, quarantine/unlink and fsync. Even dry run requires admission. |
| `case_attachments.storage_bindings.binding_locks/migrate_original` | Admission before digest locks and before case transaction; transition row and pointer change commit before release. |
| `delivery_queue.services._postgres_only` | `require_admission()` also executes on the nested queue fast path, before ownership/connection checks. |
| `composite_delivery.simulator.event` | Calls queue preflight; only local signed fixture result, no external send. Caller must already be admitted. |
| `intake_workflow.management.commands.migrate.Command.handle` | Decorated whole command, plus pre-migrate ownership/admission signal. Direct MigrationExecutor remains a prohibited bypass. |
| `platform_recovery.integration.offline_restore_files` | Existing nonce/OID/owner-proven, live operation lease for an exclusively new restore target; source DB admission never granted. V12 additionally refuses GC in this exception. |

## HTTP, GET, HEAD and sessions

- `config.settings.campaign_review.MIDDLEWARE` currently places
  `apps.platform_recovery.middleware.MaintenanceGuard` first; keep it outside
  `PreviewCompositionGuard`/`CaseworkGuard`, CSRF and any future session middleware.
  All methods, errors and response construction are enclosed; streaming responses are
  closed/rejected inside admission rather than executed later.
- `casework_web.guard._budget` performs real throttle-row writes on GET/HEAD as well
  as POST. It currently relies on the outer middleware (see required hook below).
- `casework_web.access` and `requester_workspace` use signed HttpOnly cookies, not
  a Django DB session table. Staff login/logout, requester capability cookies, source
  filter cookies, CSRF creation/rotation and expiry/error responses are within HTTP
  admission. No claim that database sessions were tested when no such backend is installed.
- `library_preview.guard.PreviewCompositionGuard` has a read-only preview prefix,
  but the maintenance middleware still surrounds it. No GET exemption is added.
- Current private-file routes return in-memory private responses. Future streaming,
  async/background tasks and response-close signal writers need their own explicit
  lifetime design/admission; a returned iterator cannot borrow an expired lease.

## Required integration changes outside this lane

| File/function | Required change | Reason |
|---|---|
| `apps/answer_media/services.py:clone_parts_for_new_answer` | Add `require_admission()` at entry, before ORM; retain callers’ existing locked transaction. | Internal helper creates manifests/parts without its own admission assertion. Do not add an outer decorator inside the existing transaction. |
| `apps/case_citations/services.py:clone_citations_for_new_answer` | Add the same assertion before ORM. | Internal clone inserts citations; database lineage checks do not replace admission. |
| `apps/casework_web/guard.py:_budget` | Add `require_admission()` before ownership lookup/transaction. | Prevent a direct/composed guard call from writing when the top middleware is omitted. |
| Management dispatch / command modules owned by integrator | Invoke `admission.require_supported_command(name)` before command body; use `admission.run_management_command` for application call sites. Install explicit refusing command overrides for `flush`, `loaddata`, `clearsessions`, `dbshell`, `shell` if those stock commands remain reachable with the required flag. | Hook is supplied and tested here; it is not globally installed by this lane. Unknown commands fail closed. A wrapper only in manage.py cannot intercept direct call_command. |
| V12 profile/verification | Keep required=True and one initialized control/private root bound to the owned DB in every HTTP/worker/CLI process; register both test modules and commands below. | Flag-off legacy profiles remain compatible and are not a claim of maintained operation. |

## Separate historical stores: excluded, not silently covered

Inspected `delivery_planner/outbox.py` SQLite `_db` commits in `stage_plan`,
`reserve_for_adapter`, `record_provider_receipt`, and `outbox_recovery.flag_expired_reservations`.
Inspected `fast9_case_source_join/source_journal.py` SQLite initialization/migration,
`acknowledge_review`, `record_clarification`, `append_source_event`, `issue_reply_code`,
`revoke_reply_code`, `submit_requester_reply`, `save_answer_draft`, `record_draft_note`
(with answer_drafts/reply_access helpers). They have synthetic flags but no maintenance
admission. Do not enable these separate legacy stores in the maintained V12 pilot;
if retained as callable administration, the integrator must explicitly refuse them
when maintenance is required. Wrapping them would not put their SQLite files into
the PostgreSQL+private-original recovery manifest.

`fatwa_drafts.domain` is explicitly in-memory synthetic staging, not a persistence
adapter. Dictionary updates in presentation/search/projection code are not database
writes. Fixture/demo generation is stopped-writer bootstrap, not a permitted live
administrative command. Recovery service/encrypted/admin are separately authorized
offline operations: capture uses FROZEN, restore targets are fresh and proven, no
source-writer lease is fabricated. Their internals were not edited here.

## Limits

This inventory covers repository-defined canonical paths and identified legacy bypasses.
It cannot prevent raw ORM/SQL, arbitrary imported Python, modified runtime code, direct
MigrationExecutor, independently connected clients or a privileged DB user. No OS/DB
privileges were changed. Integration remains incomplete until the hooks above land.
New entrypoints require review; calling status() once is never admission.

Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.
No percentage or acceptance uplift is assigned.
