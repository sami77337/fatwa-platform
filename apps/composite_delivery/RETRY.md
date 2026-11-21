# Explicit bounded retries for a failed composite part

Original requirement **127** is implemented as a default-off development
extension to the existing signed delivery queue. The native desk can export a
new approval request for one failed part and accept the independent signed
response. There is no external sender, automatic retry or new queue engine.

## Exact behavior

Only `FAILED_REQUIRES_REVIEW` with a cryptographically verified stored provider
failure can have a successor. Staged, leased, accepted, delivered and unknown
outcomes cannot be retried. Each original part permits at most **three**
additional attempts. Every additional attempt requires its own fresh signed
human approval, issued after its predecessor's recorded failure. Repeating
the exact current request and signature returns the same binding; another
request cannot fork the predecessor.

`CompositeRetry` is an append-only binding between the original composite
delivery, failed parent intent, signed failure evidence and new approval claim.
The new claim has exactly one normal queue intent. That intent's queue ordinal
is **1**; the signed scope separately retains the original logical ordinal,
part UUID, raw content hash, complete approved manifest, selection mode,
original plan, origin, channel capability hash and recorded approver identity.
The existing worker resolves the exact original bytes through that explicit
binding. The offline simulator also verifies both ordinals before signing its
reported outcome.

The original failed intent, immutable attempt, receipts, audit events and
original queue summary remain unchanged. The staff projection reports the
effective leaf of each part's validated chain and includes the original plan's
failed state. Provider acceptance remains distinct from verified delivery.
An explicit text-only plan continues to exclude its omitted original files
from every initial or retry attempt.

Case closure requires verified delivery for every selected part's current
leaf. Only the exact verified ancestor chain can reconcile an older failed
claim. Unrelated, unbound or unresolved historical claims still block closure;
success of a newer answer cannot conceal an older unresolved failure.

## Current authorization and integrity

`FATWA_COMPOSITE_RETRY_ENABLED` must be literal `True` in the owned synthetic
environment. The current configured identity provider, canonical approver,
source facts, channel capabilities and provider verifier are rechecked under
the existing case and queue locks. New reservations and signed staging require
the currently configured approval verifier. Native forms also require CSRF,
the exact case/evidence/plan versions and explicit confirmation. Retained
identity and verifier pins cover final rendering; late revocation rolls back
the new signed claim, intent and retry binding together.

The new table is `composite_delivery_compositeretry`. Migrations add unique
parent and per-part retry-number constraints, a strict 1–3 bound and
`composite_retry_guard()`. `composite_retry_scope` checks canonical context,
signed failure ancestry, full-scope hashes, current source pins and the one-part
queue binding. `composite_retry_immutable` rejects update/delete. A populated
retry schema cannot be removed by migration reversal.

## Native contracts and evidence

The existing staff dispatcher discovers two additional actions through
`apps.composite_delivery.views.ACTIONS`: `composite_retry_export` and
`composite_retry_stage`. They use the original case/plan pins plus `part_id`,
`parent_intent` and the stable UUID `request_id`. The stage action additionally
requires `confirm=yes` and `response_json`. No new public URL is added.

The PostgreSQL contracts cover exact bytes and ordinals, bounded failures,
signature/current-trust denials, one-winner concurrency, idempotent repeats,
SQL forgery and immutable history, populated migration reversal, native forms,
final-render rollback, text-only composition and conservative case closure.

The combined 56-test service/native HTTP/lifecycle/selection recovery suite
passed on fresh PostgreSQL 17 and 18 clusters (90.812 and 91.139 seconds).
After the final configured-verifier pin checks, all 15 retry, retry recovery and
retry closure tests were rerun and passed on both majors (42.739 and 42.887
seconds). Those 15 are included in the earlier 56; they are not additional
distinct tests. Ruff, Django's system check and the migration-drift check pass.

`retry_recovery.populate()` creates two real retry rows and three signed plans
for one original three-part answer. `verify_restored()` uses a fresh connection
and freshly constructed current trust with only a public verification key.
It checks the original bytes and retained failed history, six trust denials,
positive reads after restoration, and unchanged canonical/queue/audit rows.

Protected browser identity:
`apps.composite_delivery.browser_retry.CompositeRetryBrowserTests.test_native_failed_part_fresh_signed_bounded_retry_keeps_original_failure_and_no_duplicates`.
Proof: `.local/qa/functional-continuation/composite-retry-browser/result.json`,
with `trace.zip` and screenshots at 320/1280 pixels. The journey enters signed
outcomes through native forms, exports the actual retry request, stages a fresh
signed approval, resolves exact audio bytes, distinguishes accepted from
delivered, retains the original failure and denies a revoked current reader.
The queue desk does not render a playback control and does not claim browser
audio playback. Protected browser completion requires the hosted run; local
code and PostgreSQL results alone do not count the original point as completed.

**NOT_DEPLOYED**. Gate B **NOT_PASSED**, C/D/E **HOLD**, Phase01 **BLOCKED**.
Synthetic approvals and fixtures do not authorize real transport, publication,
requester data or production migrations.
