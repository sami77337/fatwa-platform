# Current-case delivery follow-up (synthetic)

This slice continues #214 (`efff2a979b0f3b81b7f557740996e91c87628810`).
It adds operational follow-up of an existing approved return plan, without
reimplementing approval, planning, signature verification, staging or sending.

Before: the queue could quarantine expired worker leases globally, and the case
bridge exposed aggregate delivery evidence. There was no case-scoped maintenance
operation or per-part explanation for the responsible Mufti.

Now: a scoped staff service reports each current part's queue state, expiration,
verified provider evidence and next safe action. A separate explicit operation
moves only expired leases of the exact displayed plan to
`UNKNOWN_REQUIRES_RECONCILIATION`. It preserves the original attempt so a late
signed provider result can reconcile it through #214. It never requeues or retries
an uncertain/failed part, renews approval, contacts a channel or claims reading.

## File ownership and integration

New application code: `apps/casework/delivery_reconciliation.py` only.
Shared queue change: optional `plan_fingerprint` filter in the existing
`quarantine_expired_leases`. Omitting the filter preserves existing behavior.
Tests: `tests/casework/test_delivery_reconciliation.py`; the existing #214 fixture
helpers moved into `delivery_fixtures.py` for reuse without duplicated test IDs.
The V6 workflow adds this test module. No models, migrations, configuration,
requester workspace, team workspace, views, templates or routing are changed.

UI owners can import:

```python
from apps.casework.delivery_reconciliation import (
    read_case_delivery_followup,
    quarantine_case_delivery,
)

# All identity/verifier objects are configured by the server, never form fields.
report = read_case_delivery_followup(
    case_id=case_id, subject_id=subject_id, provider=trusted_directory,
    verifier=trusted_provider_verifier, synthetic_fixtures_only=True,
)

# An explicit staff action must submit the displayed plan hash, not just case_id.
result = quarantine_case_delivery(
    case_id=case_id, subject_id=subject_id, provider=trusted_directory,
    expected_plan_sha256=report["plan_sha256"],
    verifier=trusted_provider_verifier, synthetic_fixtures_only=True,
)
```

Both operations reuse #214's current-case lock, original approving Mufti identity
and epoch, exact immutable binding, synthetic database guard and final identity
recheck. A new answer/follow-up/clarification or different plan makes the old action
fail. An unauthorized actor cannot inspect or mutate delivery state.
`expected_plan_sha256` prevents a stale form from targeting a replacement plan.
The mutation uses server time and has a fixed 16-part bound; no caller clock or
caller-selected queue scope is accepted.

The report schema is `fatwa.case-delivery-followup.v1`. It includes scoped staff
case/plan/version metadata, `queue_state`, `delivery_status`, `delivery_verified`,
`authorization_expired`, `expected_parts`, `quarantinable_parts`, and `parts`.
The mutation adds `quarantined_parts`. `read_confirmed` and
`automatic_retry_allowed` are always false. The report contains no answer/question
text, requester token/identity, receipt/signature, intent key or worker credential.
This is a staff projection, not a public/requester response.

| `next_action` | Meaning |
| --- | --- |
| `TRUSTED_RESERVATION_REQUIRED` | Staged part; use #214's current signed-approval worker path if authorized. |
| `NEW_MUFTI_REVIEW_REQUIRED` | Staged part's return approval expired; this service cannot renew it. |
| `AWAIT_PROVIDER_OUTCOME` | Live lease or ACCEPTED; no delivery claim. |
| `QUARANTINE_EXPIRED_ATTEMPT` | Lease expired; the explicit quarantine action is available. |
| `REVIEW_PROVIDER_OUTCOME_NO_RETRY` | Unknown/failed outcome needs human examination; no automatic resend. |
| `CHECK_SIGNED_EVIDENCE` | Queue reports DELIVERED but the current provider proof is absent/unverified. |
| `NO_ACTION` | This part has a verified signed provider delivery report. |

The aggregate is verified only when both the existing provider audit and every
part verification succeed. A key revocation between those checks fails closed.
Missing verifier allows operational inspection, but never verified delivery.

Use POST + CSRF, the current scoped staff session and private/no-store responses
when wiring the mutation. Render fixed Arabic descriptions for the codes rather
than raw exceptions; handle `CaseConflict`, `QueueConflict`, `InvalidPlan` and
database failures using the existing safe error boundary. No endpoint is enabled
by this change.

## Concurrency and evidence

Local verification: **89/89 affected tests PASS** on Python 3.13.5 / Django 5.2.18 /
PostgreSQL 17.11, no skips: 18 new reconciliation tests, 25 unchanged #214 bridge
tests and 46 existing queue/provider tests. Ruff, formatting of new/refactored
files, Django system checks and whitespace checks passed. CI registration adds
the new module to the existing V6 PostgreSQL 17/18 matrix; its result is separate
from this local receipt.

Reads lock the queue audit head but not intent rows. Mutation locks eligible
intent rows before the audit head, following existing queue order. Busy rows use
`skip_locked`; `quarantined_parts=0` is not proof that all work is resolved—inspect
`quarantinable_parts`/part states. Repeating quarantine is idempotent and adds no
duplicate audit events. Failure or identity change rolls back all state/audit
writes. The existing immutable attempt and signed evidence tables are reused.

Tests cover live/expired/accepted/failed/partial/delivered states, scope isolation,
stale plans and facts, unauthorized roles/epochs, late signed receipts, receipt vs
quarantine concurrency, busy parts, rollback, revocation during verification,
nonmutating reads and secret omission. Run on a fresh owned synthetic cluster:

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin --major 17 -- python manage.py test tests.casework.test_delivery_reconciliation tests.casework.test_delivery tests.delivery_queue.test_postgres_queue tests.delivery_queue.test_queue_regressions tests.delivery_queue.test_queue_safety_extensions tests.delivery_queue.test_signed_provider_receipts --noinput --verbosity=2
```

No browser changes or browser acceptance is claimed. No real provider credentials,
production identity, actual sends, main merge or deployment.
**NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.**
