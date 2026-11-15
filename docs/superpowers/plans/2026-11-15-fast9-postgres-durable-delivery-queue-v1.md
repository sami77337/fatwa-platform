# FAST9 PostgreSQL Durable Delivery Queue v1

## Goal
Move the synthetic delivery queue guarantees from single-file SQLite to an isolated PostgreSQL 17/18 implementation with atomic approval consumption, concurrent worker leases, receipt idempotency and conservative reconciliation.

## Constraints
- Base: PR200 head f532611d5dfa4c113f0da78d25d78a748902371f.
- Branch: codex/20261115-fast9-postgres-delivery-queue-v1.
- Additive isolated app only. Do not register in production/public settings.
- Reuse the existing Wave7 synthetic database ownership guard and fresh test DB runner.
- No sender, provider connection, production data, deployment, merge or main edits.

## Implementation
1. Add ApprovalClaim, DeliveryIntent, ProviderReceipt and append-only DeliveryAuditEvent models.
2. Implement advisory-locked atomic approval consumption and exact plan manifest binding.
3. Implement concurrent SKIP LOCKED worker claims with expiring leases.
4. Implement atomic provider receipt persistence and exact replay handling.
5. Quarantine expired leases to reconciliation; never auto-requeue uncertain sends.
6. Add PostgreSQL 17/18 isolated CI matrix and integration tests.

## Acceptance
- Same approval and exact plan are idempotent; altered plan and reused nonce are rejected.
- Two workers claim distinct rows under concurrency.
- Receipt, intent transition and audit event commit/rollback together.
- Exact receipt replay is idempotent; changed payload is rejected.
- Expired lease is quarantined, not requeued.
- Plan complete only when all expected parts are delivered.
