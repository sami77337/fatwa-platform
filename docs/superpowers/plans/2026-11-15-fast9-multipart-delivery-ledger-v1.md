# FAST9 Multipart Delivery Ledger v1

## Goal
Aggregate delivery state for every part of one exact plan. Never report an answer fully delivered until all its parts have verified DELIVERED receipts.

## Constraints
- Base: PR196 head 248dcda81ded26f474d310ff93ff8670c5df820e.
- Branch: codex/20261115-fast9-multipart-delivery-ledger-v1.
- Synthetic fixtures only; read-only summary, no send, no network, no production.
- Preserve prior PRs and schema v2.
- Do not edit AGENTS.md or docs/coordination/**.

## Implementation
1. Add immutable PlanDeliverySummary projection in outbox_recovery.
2. Group by exact persisted plan fingerprint.
3. Report counts and per-part states; derive conservative aggregate state.
4. Add tests for empty store, partial success, full success, partial failure and uncertain expired reservation.
5. Include tests in FAST9 integrated CI and document limitations.

## Acceptance
- One delivered part never marks a multi-part plan complete.
- All parts must have verified DELIVERED state for complete=True.
- Mixed success/failure is PARTIALLY_FAILED.
- Expired unresolved part forces NEEDS_RECONCILIATION.
- Summary is read-only and does not create absent store.
