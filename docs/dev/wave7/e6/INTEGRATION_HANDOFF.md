# E6 required producer contracts — proposal pending actual code

The delegation's full-leadership-spec field was `undefined`; this increment uses
the attached lossless contract and the accepted foundation only. This is a
bounded request for exact integration details, not a request to reopen foundation.
Other producers were still in progress; no arrival/API is assumed.

E6 owns `workflow_contract.py` as its test adapter boundary. Its proposed
`WorkflowScenario` carries actual persisted batch UUIDs, per-item detail GET paths,
the repeated external ID, exact original questions, a blocked detail path and a
reviewed detail path. `prepare_workflow_scenario()` currently raises
`E1_E2_E3_E4_ACTUAL_SERVICES_AND_GET_HOOKS_PENDING`. It cannot report acceptance.
E6 will replace this boundary only after reading actual producer implementations.
There is no production stub, second importer, migration or alternate source map.

Required from root/owners:

1. **E1:** exact import/service and CLI signatures plus receipt fields for actual
   batch intake, same-key exact-byte replay and changed-payload conflict. E6 must
   create two batches (same external ID, different exact original question),
   replay without duplicate items/refs, reject changed bytes and inspect from a
   new process. Commands/services run outside HTTP and own their guarded unit.
2. **E2:** actual review service/command signature, operation replay/conflict and
   stale-state/concurrent-call error contract. E6 must start/request changes/start/
   complete internal review, verify persisted synchronized state/events and retry
   after process restart without duplicating events. No answer/approval action.
3. **E3:** actual persisted reference-resolution entrypoint and result fields.
   Include verified vs unverified/mismatched/invalid original pointers, exact
   SourceSlice provenance and citation escaping; readiness is separate from source
   verification. Fixture seeding must remain outside another guarded transaction.
4. **E4:** actual read-only list/detail paths, allowed filter/page/sort/batch query
   keys, native search/filter controls and stable item/event/citation hooks. Needed
   browser checks: batch switch, repeated-ID detail isolation, blocked rows visible,
   filter/page/detail/return/back/forward/reload, keyboard and rapid-navigation
   races, exact originals and review event display, errors/empty results, desktop
   and 390/320 mobile, no media/network/console violations. E6 will adapt selectors
   to actual hooks; these are proposed test needs, not permission to add HTTP writes.
5. **E5:** actual separate test/dev setting module and default-off integration
   flag for those GET routes, standard protected CI Chrome executable, and explicit
   E6 labels/artifact wiring documented in README. Current frozen wave7_test with
   the generic Wave7TestRunner successfully runs the six baseline E6 DB tests on
   PG17/18; existing CI labels alone do not discover them. No E5 file edited here.

These full workflow journeys are NOT_IMPLEMENTED/NOT_RUN in this baseline
increment. The mandatory workflow label deliberately fails pending actual hooks.
Do not treat an E6 baseline PR or storage probe as full Wave7 acceptance.

Artifacts: `E6_WAVE7_ARTIFACTS` holds sanitized baseline JSON (SHA/dirty paths,
command/versions, per-case statuses, actual asset200/MIME/bytes checks, sandbox
stderr and screenshots only after real interaction). `workflow-result.json`
records the pending integration instead of a passing fallback. CI should collect
that directory even when a gate fails.
