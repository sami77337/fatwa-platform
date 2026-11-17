# Case delivery evidence integration (synthetic only)

Base reviewed: #209 `e000cdc22c1a0dfd1e0e38eb8fd7cfbfc392487e`, including
#208 `23839110af15baf09ed80b1002a328021cea5e31` and #207
`27d790fe67970f5e8d94dfc280233228dff3aa34`. `main` was
`fcdc20e1c8f8849e65b9b912d695cb87ab9a0280` (README only). The later campaign
commit `57d72abe355a2a6b7675279d4d68cd2b1d596ab1` changes public search only;
it is outside this slice. No main merge or deployment.

The existing `CaseDecision` records scholarly approval. This bridge additionally
requires an Ed25519 approval for returning the exact plan, from the same Mufti,
directory and authorization epoch. It reuses the existing planner, segmentation,
approval adapter, PostgreSQL queue and signed provider evidence audit. No signer
or outbound transport is added. Test keys are generated only in test memory.

## Integration contract

All functions live in `apps.casework.delivery`. Staff calls use the established
`case_id`, `subject_id`, trusted `MuftiIdentityProvider` as `provider`, and explicit
`synthetic_fixtures_only=True`. Neither provider nor verifier may come from a
browser payload. Existing casework views and templates are unchanged.

| Function | Additional arguments | Result |
| --- | --- | --- |
| `prepare_case_delivery` | `max_chars=6000`, `split=False` | Read-only `REQUEST_NOT_APPROVED`, `decision_id`, `evidence`, `plan`, `plan_sha256`, options. No signature issued. |
| `stage_case_delivery` | Same options, `receipt: SignedApprovalReceipt`, `verify_receipt: Ed25519ApprovalVerifier` | Atomically saves the queue manifest/context and immutable `CaseDelivery` binding. Returns `STAGED_NOT_SENT` or `ALREADY_RECORDED`, `plan_sha256`, `part_count`. |
| `reserve_case_delivery` | `worker_id`, trusted `verify_worker`, `verify_receipt` | Existing `WorkerLease` or `None`; verifies current case, original approver epoch, signed plan and worker. |
| `resolve_case_delivery_text` | `lease`, `verify_receipt` | Existing `TextSegment`; `exact_text` preserves the human-authored content. Internal adapter readiness only, no send. |
| `record_case_provider_event` | `lease`, `event: SignedProviderEvent`, `verifier: Ed25519ProviderEventVerifier` | Existing queue `DeliverySummary`. Only the current case plan/part/attempt can accept the signed report. |
| `requester_delivery_status` | `token`, optional server `verifier`, synthetic acknowledgment | Private case status with `delivery_status`, `delivery_verified`, `read_confirmed=False`; verified audits also include `expected_parts` and `verified_parts`. No internal identifiers or answer text. |

The external synthetic signer uses the exported `evidence`'s case/answer/source/
reply fields and the exact `plan_sha256` in the existing `SignedApprovalReceipt`
contract. It must use the case's approving Mufti identity. The origin is derived
from the case; there is no caller-controlled recipient or channel. `website` and
`casework-synthetic.v1` describe a declared test capability, not a live provider.

`services.requester_status` retains its prior conservative behavior for callers
that have not opted into the bridge. Interface owners can explicitly call
`requester_delivery_status` under their existing POST/CSRF/no-store/rate-limit
boundary. Do not display `REQUEST_NOT_APPROVED` or `STAGED_NOT_SENT` as delivery.

Safe requester delivery states:

- `CURRENT_APPROVAL_REQUIRED`: current facts/answer have no valid case approval.
- `NOT_STAGED`: scholarly approval exists but no bound return plan exists.
- `EVIDENCE_UNAVAILABLE`: no trusted verifier or inconsistent evidence.
- `NOT_FULLY_DELIVERED` / `NEEDS_RECONCILIATION`: no complete signed delivery.
- `PROVIDER_EVIDENCE_INCOMPLETE`: queue delivery exists without all signed proofs.
- `PROVIDER_REPORTED_DELIVERY_VERIFIED`: every expected part has a valid signed
  provider report bound to its original attempt. This does **not** prove reading,
  receipt on the person's device, or authorize publication.

Use the existing fixed `CaseConflict`, `QueueConflict`, `InvalidPlan` denials and
database exceptions; never echo receipts, tokens, case text or exception internals
to the requester. Missing/expired/revoked access tokens remain denied.

## Persistence and concurrency

`CaseDelivery` links one immutable case decision to one existing `ApprovalClaim`.
`0003` adds the table; `0004` adds immutable and cross-case/current-approval guards.
No existing case or queue rows are rewritten. Guard rollback `0004 → 0003 → 0004`
preserves populated bindings and signed evidence; reversing `0003` drops the new
table and is **not** a preservation operation.

The case row is locked before queue locks. Staging writes the binding, claim,
signed context, intents and audit in one transaction. Follow-up/new answer/
clarification invalidates the current projection without deleting historical
proof. Old receipt or plan substitution is rejected; replay of the same current
receipt is idempotent, and one decision cannot acquire an alternative return plan.

`delivery_queue.services.synthetic_queue_atomic()` runs the original database
ownership guard before starting the transaction. Nested service checks are bound
to that exact live connection and atomic block, recheck environment/configuration,
and are cleared on exit. Arbitrary caller transactions, stale copied contexts,
changed connections and changed production flags fail closed. This is required
to compose the existing guarded services without splitting the commit.

## Validation and limits

Local result on Python 3.13.5 / Django 5.2.18 / PostgreSQL 17.11: **133/133 PASS**,
including **25 new bridge tests** and 108 existing affected tests, no skips.
Ruff, `git diff --check`, Django system checks and migration drift checks passed.
The first bridge run exposed the nested ownership-guard rejection; composition
was implemented without removing the guard, then negative scope tests passed.
PostgreSQL 18 is not locally installed; its CI result must be checked separately.

Focused new tests: `tests.casework.test_delivery`; full synthetic journey, two
case isolation, ACCEPTED/partial/unsigned proof refusal, wrong case/facts/answer/
part/attempt/signature, revoked keys, stale approval, callback failure, access
rotation, concurrent staging/follow-up, rollback and populated guard migration.
The existing V6 CI matrix now includes this module on PostgreSQL 17 and 18.

Local reproduction (fresh disposable cluster only):

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin --major 17 -- python manage.py test tests.casework.test_delivery tests.casework.test_core tests.casework.test_adversarial tests.casework.test_tracking_bridge tests.delivery_queue.test_postgres_queue tests.delivery_queue.test_signed_approval_bridge tests.delivery_queue.test_postgres_audit_attestation tests.delivery_queue.test_signed_provider_receipts tests.delivery_queue.test_trusted_journey tests.delivery_queue.test_queue_regressions tests.delivery_queue.test_queue_safety_extensions --noinput --verbosity=2
```

Only affected backend tests are run locally. No UI changes or browser claim.
The existing text adapter accepts at most 6000 characters and 16 parts; longer
answers fail closed, and segmentation requires explicit human choice. Operational
identity, channel credentials, real sends and production activation remain absent.

**NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.**
