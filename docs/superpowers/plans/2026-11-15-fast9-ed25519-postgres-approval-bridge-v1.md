# FAST9 Ed25519 MUFTI Approval to PostgreSQL Queue Bridge v1

## Goal
Connect the existing Ed25519 signed MUFTI approval verifier to the PostgreSQL atomic approval-consumption service, so callers cannot pass arbitrary approval fingerprints directly without a signed receipt verification boundary.

## Constraints
- Base: PR201 head ce55b5c672599fcdd1c11aa4ebff8f3aeede25b3.
- Branch: codex/20261115-fast9-ed25519-postgres-approval-bridge-v1.
- Synthetic keys and identities only; no live identity provider, KMS, sender, deployment or merge.
- Keep the adapter out of production settings.

## Implementation
1. Add commit_signed_approved_plan wrapper.
2. Verify Ed25519 receipt through require_return_approval before PostgreSQL commit.
3. Bind exact plan fingerprint and ordered step idempotency keys to the signed plan.
4. Consume receipt ID and nonce atomically through PostgreSQL queue.
5. Add tests for valid receipt, exact replay, changed plan, revoked/inactive MUFTI, tampered signature and unsigned receipt.
6. Include tests in PostgreSQL 17/18 matrix.

## Acceptance
- Valid signed MUFTI receipt creates one claim and exact intents.
- Exact replay is idempotent.
- Changed plan, revoked nonce, inactive identity, tampered signature and unsigned receipt create no claim.
- PostgreSQL 17/18 suites pass.
