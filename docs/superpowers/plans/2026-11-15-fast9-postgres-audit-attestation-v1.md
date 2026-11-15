# FAST9 PostgreSQL Audit Hash Chain & External Attestation v1

## Goal
Make PostgreSQL delivery audit events hash-linked and externally checkpointed, so rebuilding the local event chain cannot silently replace a previously trusted audit head.

## Constraints
- Base: PR202 head 188f036aeb97f8e32e46fd4b177a8a3162cc8056.
- Branch: codex/20261115-fast9-postgres-audit-attestation-v1.
- Test-only HMAC keys; no KMS/WORM integration, sender, production data, merge or deployment.

## Implementation
1. Add DeliveryAuditHead singleton and sequence/previous_digest/digest to DeliveryAuditEvent.
2. Append each event and advance the locked head in the same transaction.
3. Verify the entire chain before every queue mutation and plan summary.
4. Add external HMAC checkpoint with key ID and caller-supplied external key.
5. Add tests for valid checkpoint, tampered claims, stale checkpoint, rebuilt local chain, and key rotation.
6. Add PostgreSQL 17/18 CI coverage and migration-state verification.

## Acceptance
- Hash chain validates all events and head.
- Mutating and rebuilding the local chain changes the head and invalidates old external checkpoint.
- Unknown/retired/wrong keys and altered claims fail closed.
- PostgreSQL 17/18 tests pass.
