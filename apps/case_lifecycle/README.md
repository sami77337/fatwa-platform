# Non-destructive case lifecycle — owner points 385–386

This unit adds native CLOSE / REOPEN / ARCHIVE / RESTORE workflows to the existing
synthetic case application. It does not edit `Case.stage`, change an approved
answer, send a message, publish content, or delete source records. The case keeps
its original public reference. A genuine canonical requester FOLLOWUP reopens a
closed or archived case and records the exact source event.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.** All actions
still require the owned synthetic database and existing current scoped MUFTI
identity. No organizer permission, production role hierarchy or retention policy
is inferred. The new feature and authority default to `False` and `None`.

## Exact owner scope

| Original point | Implemented functional meaning | Specification |
| --- | --- | --- |
| 385 — CLOSED does not mean ARCHIVED | Explicit closure and reopening, an ordinary-work queue distinct from the closed list, preserved source/answer history | SPEC-U14-020; SPEC-U01-027/028/029 |
| 386 — ARCHIVED does not mean SOFT DELETE | Archive only a closed case, view its authorized history, restore to CLOSED, then explicitly reopen if work should resume | SPEC-U14-020; SPEC-U01-029 |

D-043 permits these distinctions; detailed retention remains unresolved. No new
credit is claimed for pre-existing followups, private access, delivery or audit
features. Points 387–390 (soft deletion, unpublication, anonymization and purge)
are not implemented or claimed here. Data sensitivity is a separate unit.

## States and closure evidence

The lifecycle is orthogonal to canonical scholarly workflow:

- No event means OPEN. CLOSE moves OPEN to CLOSED.
- ARCHIVE moves CLOSED to ARCHIVED. RESTORE moves ARCHIVED back to CLOSED.
- REOPEN moves CLOSED to OPEN without invalidating the approved answer.
- A valid new canonical requester FOLLOWUP moves CLOSED or ARCHIVED to OPEN.
  Existing casework alone changes evidence and invalidates the old approval;
  lifecycle merely records the same-case return to work.

CLOSE requires the exact current approved answer and its still-current scoped
scholarly approver. A current signed-delivery plan must have verified delivery for
every part. Staged, leased, accepted, failed, partially delivered, unknown and
unsigned delivery cannot be called complete. Legacy and composite plans use
their own independently configured provider verifiers and immutable bindings.
Any unresolved historical delivery plan also blocks closure. A historical plan
cannot prove that a newer answer reached the requester.

If no delivery plan exists, closure requires **both** `CLOSE` and the separate
`CLOSE_WITHOUT_DELIVERY` permission, plus a distinct explicit native checkbox.
History says that this closure makes no delivery claim. Neither authorization nor
the checkbox alone suffices. This path is unavailable when an existing plan is
pending or unresolved. Closure never proves reading/listening and never creates
a provider receipt.

Every command supplies a reason, current canonical revision/evidence version,
lifecycle version, and an idempotency UUID. Identical command replay returns its
historical receipt without adding a row; changed replay conflicts. Concurrent
commands serialize on the canonical case and check the independent lifecycle
version. Database constraints and triggers reject UPDATE/DELETE, invalid
transitions, stale pins, cross-case answers and forged followup relationships.

## Trusted authority and read boundaries

`LifecycleAuthority.permits(...)` authorizes exact independent actions READ,
CLOSE, REOPEN, ARCHIVE, RESTORE and CLOSE_WITHOUT_DELIVERY. It receives the current
actor/provider/epoch, case reference, case/evidence/lifecycle versions, current
state, exact approved-answer identity and previous lifecycle hash. It does not
grant case access, scholarly approval, delivery or publication permission.

`projection_epoch()` must be an atomic, side-effect-free revision of **all** grant
inputs. Permission callbacks that change a grant must advance it. There is no
permissive default or authorization from a browser-supplied role.

Read projections snapshot case, lifecycle, plan, binding and receipt state before
any permission/row callbacks. They pin the authority and directory objects by
identity, their relevant epochs, and both provider verifier configurations.
Final checks run after permission callbacks and actual native rendering, so
nested lifecycle writes, new facts, scope reduction, revocation, flag changes and
policy replacement reject the whole response. A valid identity-expiry refresh
alone is accepted. Multi-case projections lock in UUID order and filter permission
before counts/search results.

`desk` and `inbox` return a `_guard` for callers composing additional rendering.
The supplied native views retain the outer queue transaction and case locks
through that rendering. Callers must not serialize `_guard` or treat a DTO from a
completed transaction as a permanent permission.

## Coordinator integration — shared files are not changed in this lane

1. Register `apps.case_lifecycle` in the synthetic campaign. Apply migrations
   `0001_initial` and `0002_integrity`. The standalone settings deduplicate this
   registration so the later shared registration is safe.
2. Default `FATWA_CASE_LIFECYCLE_ENABLED=False` and
   `FATWA_CASE_LIFECYCLE_AUTHORITY=None`. Configure only explicit synthetic grants
   in the owned fixture/demo. Do not install a fixture authority in production.
3. Delegate `views.ACTIONS` at the existing CSRF/session/loopback guarded
   `/casework/staff/` route. Actions are `lc_open`, `lc_inbox`, `lc_filter`,
   `lc_close`, `lc_reopen`, `lc_archive`, `lc_restore`. The standalone overlay is
   `apps.case_lifecycle.urls`. Add native navigation to `lc_inbox`, and the
   `case_lifecycle/entry.html` include with `lifecycle_enabled` and
   `lifecycle_case_ref` in the selected case.
4. At the start of `apps.casework.services._event`, **before** the `if not initial`
   branch saves Case, call `before_canonical_event(case=case, action=action)` when
   the lifecycle app is installed and enabled. It requires OPEN only for
   SAVE_ANSWER, CLARIFICATION, APPROVE and RETURN_FOR_CHANGES. Its denial rolls
   back the existing atomic canonical transaction, including a newly created
   draft. Access rotation/revocation remains independent.
5. Assign the existing `CaseEvent.objects.create(...)` result in `_event` to
   `event`. Immediately after that insert, when `action == "FOLLOWUP"` and the
   feature is enabled, call `record_followup(case=case, event=event)`. This exact
   hook covers both `casework.add_followup` and `case_attachments.upload`, which
   already use `_event` under their current requester-capability transaction.
   Do not expose this helper as an endpoint or an independent runnable principal.
6. Wrap ordinary staff queue/search rendering in `queue_projection` **before**
   computing filters, pagination or counts. Pass existing canonical staff DTOs
   and keep the context open through final rendering:

   ```python
   with queue_projection(
       rows, subject_id=actor.subject_id, provider=provider,
       synthetic_fixtures_only=True, states=("OPEN",),
   ) as visible_rows:
       response = render(request, template, build_context(visible_rows))
   return response
   ```

   The helper checks each input row's canonical revision/evidence pins before
   using it. It never expands input scope. The dedicated lifecycle list can
   select OPEN/CLOSED/ARCHIVED/ALL independently. Direct authorized historical
   case viewing stays available; new staff work requires explicit reopening.
7. Add the one durable table and guard function/trigger below to encrypted
   recovery inventory. Compose `recovery_support.populate()` into the fixture
   and call `verify_restored(pins)` in the fresh restored process. Policies are
   reconstructed from explicit synthetic scope; no capability or signing key is
   serialized. The seed uses real services to create CLOSED, ARCHIVED and
   FOLLOWUP-reopened cases, with six nonempty immutable lifecycle events.

## Inventory and service signatures

- Table: `case_lifecycle_lifecycleevent`.
- Function: `lifecycle_event_guard()`.
- Trigger: `lifecycle_event_guard` on that table.
- `command(case_id, action, reason, expected_revision, expected_evidence_version,
  expected_version, command_id, without_delivery=False, subject_id, provider,
  synthetic_fixtures_only=False)` returns the immutable event receipt.
- `desk(case_id, subject_id, provider, synthetic_fixtures_only=False)` returns
  current state, permitted controls and chronological history.
- `inbox(state="ARCHIVED", query="", subject_id, provider,
  synthetic_fixtures_only=False)` returns authorized counts and filtered rows.
- `queue_projection(rows, states=("OPEN",), subject_id, provider,
  synthetic_fixtures_only=False)` is a context manager, not a detached list filter.
- `projection_boundary(...)` is available for additional native compositions.
- `before_canonical_event(case, action)` and `record_followup(case, event)` are
  internal keyword-only hooks in the existing canonical transaction.

When the feature was disabled during a canonical change, re-enabling cannot
silently present stale CLOSED/ARCHIVED metadata: an unmatched evidence/answer
change fails closed as `lifecycle_canonical_reopen_missing`. This is a missing
integration/reconciliation condition, not permission to rewrite history on read.

## Verification

Focused labels: `apps.case_lifecycle.tests`, `apps.case_lifecycle.test_delivery`,
`apps.case_lifecycle.test_recovery`. These use real owned PostgreSQL databases,
actual canonical services and cryptographic provider fixtures. Native HTTP tests
exercise CSRF-bound forms, explicit no-delivery consent, independent actor grants,
stale forms, HTML escaping, close/archive/restore/reopen and late-render rollback.
Concurrency and SQL mutation/transition tests do not mock the database. Callback
tests perform actual nested lifecycle writes, then verify the outer rejection
rolls them back.

The initial PostgreSQL17 run passed all 27 service/delivery cases; its six HTTP
cases failed before issuing requests because the test helper was called without
its page argument. The helper invocation was corrected and all six HTTP cases
then passed. The expanded focused suite passed **40/40** on PostgreSQL **17.11**
(11.415s) and **40/40** on PostgreSQL **18.7** (11.504s), Python3.13 / Django5.2.18,
on 2026-11-20. Both runs applied the real migrations and completed Django checks.
Those are the same 40 distinct cases on two supported majors, not 80 new tests.

The ready protected browser label is `apps.case_lifecycle.browser_tests`. It uses
the actual `config.campaign_urls`, visible native forms and the integrated
canonical hooks: close → archive → archive list → restore → reopen → archive →
requester followup → return in the normal staff queue. Fixture code only prepares
the approved synthetic case and trusted identities. Its fixed protected browser
settings never accept a sandbox-disabling environment switch. Output is
`.local/qa/functional-completion/lifecycle-browser/result.json`, trace and RTL
screenshots at widths320/1280. It is **not run locally**: protected browser startup
is already unavailable in this workspace; hosted integration owns execution.

Protected browser evidence and shared integration hooks remain coordinator-owned
acceptance steps. No local sandbox bypass is used or suggested by this lane.
