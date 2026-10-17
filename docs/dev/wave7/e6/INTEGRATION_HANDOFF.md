# E6 required producer contracts — proposal pending actual code

The recovered complete leadership specification has now been received and
reconciled, preserving the existing work and exact accepted foundation34355.
Final clarifications override earlier scope/reference/nonempty-DB wording;
the accepted lossless contract overrides the earlier source field types.
No storage/guard/application behavior change is needed in this lane.
Other producers remain in progress; actual code is read before binding hooks.

E6 owns `workflow_contract.py` as its test adapter boundary. Its proposed
`WorkflowScenario` carries actual persisted batch UUIDs, per-item detail GET paths,
the repeated external ID, exact original questions, a blocked detail path and a
reviewed detail path. `prepare_workflow_scenario()` currently raises
`E1_E2_E3_E4_ACTUAL_SERVICES_AND_GET_HOOKS_PENDING`. It cannot report acceptance.
E6 will replace this boundary only after reading actual producer implementations.
There is no production stub, second importer, migration or alternate source map.

Required from root/owners:

1. **E1:** final command/service contracts are at
   `2678b91a7c7f2e210a7585e6997725432782aa72`:
   `apps.intake_workflow.intake.check_intake(raw, *, synthetic_fixtures_only=False)`
   and `import_intake(raw, *, idempotency_key, synthetic_fixtures_only=False,
   using='default') -> IntakeResult`. Receipt fields: batch_id, decision,
   payload_sha256, item_count, reference_count, summary; report() serializes them.
   E6 now exercises import/replay/conflict from the actual API in its component
   harness; this is not final combined-SHA acceptance. E6 must
   create two batches (same external ID, different exact original question),
   replay without duplicate items/refs, reject changed bytes and inspect from a
   new process. Commands/services run outside HTTP and own their guarded unit.
   **CLI defect resolved:** the named --input regression failed on historical
   c4adc40, then passed 1/1 without DB access on final2678b91. E6 requests no E1
   rework for this issue. Keep the explicit integration regression in CI once
   E1 is assembled; missing command/flag is never an optional PASS.
2. **E2:** actual published PR61 was fetched/read at
   `b55c4596506aafd3c3d5c3a3c0fee1450fc2d2c2`:
   `transition_review(item_id, *, operation_id, action, expected_status, reason,
   synthetic_fixtures_only=False, using='default')` and
   `load_review_worklist(*, batch_id=None, row_id=None, q='', intake_status='',
   review_status='', page=1, page_size=20, synthetic_fixtures_only=False,
   using='default')`. ReviewConflict is code REVIEW_CONFLICT/status409; exact
   operation replay includes action/from status/reason. Actual template hooks:
   #stored-batch, #stored-q, #stored-intake, #stored-review, #stored-page-size;
   persisted section #wave7-persisted, p.original-text and pre.original-text.
   The approved wave7_review command delegates to that shared service.
   E6 must start/request changes/start/
   complete internal review, verify persisted synchronized state/events and retry
   after process restart without duplicating events. No answer/approval action.
3. **E3:** published PR60 module `apps/intake_workflow/references.py` is pinned at
   `5f4e66facfb672e610faed9cb7d154bed44c9510`; actual write entrypoint is
   `verify_batch_references(batch_id: UUID, *, synthetic_fixtures_only=False,
   using='default') -> BatchReferenceVerification`. Results carry batch_id,
   payload_sha256, items, each row's source and per-reference verification.
   E6's temporary component harness executes it after each E1 commit, outside
   the prior transaction. Current reference state is IntakeReference.reference_status,
   never E1.validation_results (a historical intake snapshot).
   Include verified vs unverified/mismatched/invalid original pointers, exact
   SourceSlice provenance and citation escaping; readiness is separate from source
   verification. Fixture seeding must remain outside another guarded transaction.
4. **E4/E2 read surface:** leadership preserves the existing pipeline GET.
   Root also supplied E2's additive `views.persisted_review`, named
   `wave7_editorial_review`, path `/dev/editorial-preview/persisted`, registered
   by E5 before the legacy generic route. GET uses batch/row UUID plus filters/
   page. Need published templates, native controls and actual allowed query
   keys, native search/filter controls and stable item/event/citation hooks. Needed
   browser checks: batch switch, repeated-ID detail isolation, blocked rows visible,
   filter/page/detail/return/back/forward/reload, keyboard and rapid-navigation
   races, exact originals and review event display, errors/empty results, desktop
   and 390/320 mobile, no media/network/console violations. E6 will adapt selectors
   to actual hooks; these are proposed test needs, not permission to add HTTP writes.
5. **E5:** supplied required flag is `WAVE7_REVIEW_READ_ENABLED` in separate
   Wave7 settings ONLY, default off. Need the actual published setting/route
   registration and standard protected CI Chrome executable, plus explicit
   E6 labels/artifact wiring documented in README. Current frozen wave7_test with
   the generic Wave7TestRunner successfully runs the six baseline E6 DB tests on
   PG17/18; existing CI labels alone do not discover them. No E5 file edited here.
   E2 supplied proposed collection: DB test_wave7_review_db (15) and
   test_wave7_read_db (12), pure test_wave7_review_off (4), under
   tests.editorial_demo. Counts are producer-supplied, not E6 test executions.

Approved command syntax is now known: `wave7_intake check --input <synthetic-file>`,
`wave7_intake import --input <synthetic-file> --idempotency-key <key>`, and
`wave7_review transition --item <uuid> --action <allowed-action>`. Preserve explicit
synthetic acknowledgements/guard flags; the syntax does not authorize HTTP writes.

The owned workflow adapter now uses actual E1/E2/E3 APIs and actual PR61 hooks.
`run.py --suite workflow-service` is a required two-method TransactionTestCase
for actual intake/replay/conflict/reference/review/new-process preparation and
two concurrent review processes (one success, one409, one persisted event).
The mandatory `--suite browser` now runs persisted_browser.mjs with eight real
interaction cases, not an unconditional placeholder failure. It requires actual
E5 GET registration/flag before preparing data and never creates an E6 URLconf
or a fake HTML overlay. Until E5/E4 integration and a protected engine run, full
workflow browser acceptance remains NOT_RUN. No baseline/service success promotes
that gate. E5 must wire the new workflow-service DB label separately.

Artifacts: `E6_WAVE7_ARTIFACTS` holds sanitized baseline JSON (SHA/dirty paths,
command/versions, per-case statuses, actual asset200/MIME/bytes checks, sandbox
stderr and screenshots only after real interaction). `workflow-result.json`
records the pending integration instead of a passing fallback. CI should collect
that directory even when a gate fails.
