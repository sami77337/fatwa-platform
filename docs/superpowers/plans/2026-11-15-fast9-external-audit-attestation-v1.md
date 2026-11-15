# FAST9 External Audit Attestation v1

## Goal
Anchor the local Outbox audit head with an HMAC-SHA256 checkpoint whose key is supplied and retained outside SQLite. Detect a locally rebuilt SHA-256 event chain that differs from the previously trusted checkpoint.

## Constraints
- Base: PR199 head 3ffb1386998ca9ea3f81f71b1e65c596acb9038d.
- Branch: codex/20261115-fast9-external-audit-attestation-v1.
- Test-only keys. No secrets, KMS integration, production data, network, merge or deployment.
- Preserve previous PRs and branches.

## Implementation
1. Add immutable AuditAttestation claims binding app ID, schema version, key ID, event sequence, audit digest and timestamp.
2. Sign canonical claims using HMAC-SHA256 with a caller-supplied external key of at least 32 bytes.
3. Verify signature and exact current database audit head using an explicit trusted-key map.
4. Add tests for valid checkpoint, wrong/unknown/short key, claim tampering, rebuilt local hash chain, stale checkpoint, and key rotation.
5. Add suite to FAST9 integrated CI and document operational key custody and limitations.

## Acceptance
- Valid external checkpoint matches current verified Outbox head.
- Local hash-chain rewrite is rejected by the prior external checkpoint.
- Unknown/retired/wrong key and modified claims fail closed.
- A new event invalidates the old checkpoint; a fresh checkpoint verifies.
- No key material is stored in the database or repository outside ephemeral tests.
