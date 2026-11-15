# FAST9 Trusted Identity & Approval v2

## Goal
Add a real cryptographic verification primitive and a provider-neutral contract for MUFTI approval receipts. Production identity/provider wiring remains disabled until the owner selects a trusted identity authority and supplies its issuer, audience, key lifecycle and revocation contract.

## Constraints
- Base: PR194 head c69d7feaae8d3417648e523ceb80363786b55a21.
- New branch: codex/20261115-fast9-trusted-identity-v2.
- Synthetic generated Ed25519 keys and identity records only.
- No live identity calls, private keys, production settings, sending, publication, merge or deployment.
- Do not edit AGENTS.md, docs/coordination/**, main, Phase00 evidence or Telegram bot.
- Preserve PR194 and prior branches.

## Implementation
1. Add SignedApprovalReceipt with issuer, audience, key ID, expiry, nonce and signature.
2. Add canonical Ed25519 signing payload and verifier with trusted public keys, active-MUFTI identity lookup, revocation/consumption lookup, strict UTC windows, key rotation and fail-closed behavior.
3. Verify through existing require_return_approval and outbox callback contract.
4. Add cryptographic and outbox conformance tests using ephemeral generated private keys.
5. Pin cryptography and transitive dependencies, add tests to FAST9 CI, document provider contract and limitations.

## Acceptance
- Valid signed receipt verifies and binds to exact case/revision/answer/source/reply and MUFTI identity.
- Claim/signature alteration fails.
- Unknown/retired key, wrong issuer/audience, inactive/non-MUFTI identity, expired/future/stale receipt and revoked/consumed receipt fail closed.
- Provider reader outages raise/fail closed.
- Valid receipt passes approval/outbox stage/reservation; revoked receipt creates no outbox file.
- All changed tests and full FAST9 integration checks pass on final commit.
