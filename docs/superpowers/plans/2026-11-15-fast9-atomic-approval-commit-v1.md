# FAST9 Atomic Approval & Delivery Commit v1

## Goal
Prevent reuse of one MUFTI approval receipt to stage a different case delivery plan. Commit the approval claim and all local outbox intents atomically in one SQLite transaction.

## Constraints
- Base: PR195 head af5e5759030989688e764231195bd010599919a2.
- Branch: codex/20261115-fast9-atomic-approval-commit-v1.
- Synthetic fixtures only. No identity provider, sender, network calls, merge, deployment or production migration.
- Preserve PR195 and all earlier branches.
- Do not edit AGENTS.md or docs/coordination/**.

## Implementation
1. Add append-only approval_claims table to Outbox schema v2.
2. Bind receipt ID to approval fingerprint, exact plan fingerprint, case, answer revision, source/reply digests, approver, key ID and nonce.
3. Stage claim and every plan intent in one BEGIN IMMEDIATE transaction.
4. Allow exact idempotent replay only; reject same receipt with changed plan or evidence.
5. Validate claim/intent consistency on every database read and before reservation.
6. Add concurrent duplicate/competing-plan tests and corruption/tamper tests.
7. Add tests to FAST9 integrated CI and document schema migration and distributed-transaction limits.

## Acceptance
- Same receipt + same plan is idempotent across restart.
- Same receipt + different plan is denied.
- Parallel identical submissions create one claim and one set of intents.
- Parallel competing plans yield exactly one winner.
- Claims cannot be updated/deleted and corruption fails closed.
- Existing approval, outbox, recovery and integration tests pass.
