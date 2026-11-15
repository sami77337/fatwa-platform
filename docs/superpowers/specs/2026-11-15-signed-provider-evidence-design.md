# Signed provider event evidence — development-only design

## Intent
Current queue stores verified outcomes through caller-provided boolean callbacks and PostgreSQL audit events, but cannot later independently inspect the provider's cryptographic statement. Add a strict, provider-neutral signed statement and a durable, immutable evidence record so synthetic end-to-end delivery acceptance has meaningful provenance.

## Approaches considered
1. Integrate a live WhatsApp/Telegram connector now: rejected because channels, identities and Gate B are unapproved.
2. Keep only boolean callbacks and local SHA-256: rejected because the statement cannot be independently re-verified.
3. **Selected:** offline Ed25519 signed provider event, bound to existing immutable delivery attempt and exact plan part, retained atomically next to event. Keeps all real network actions disabled.

## Interfaces
- SignedProviderEvent: issuer/audience/key/provider/plan/intent/ordinal/part_digest/attempt_digest/receipt_ref/provider_message_id/reported/times/signature.
- Ed25519ProviderEventVerifier: trusted fixed public-key map and optional live revoked-key check, bounded timestamps.
- record_signed_provider_event(lease,event,verifier): verifies signature and current immutable part, calls queue.record_receipt atomically with signed evidence, returns plan summary.
- verify_stored_provider_evidence(receipt_reference,verifier): re-verifies historical signature at saved event time, metadata and original attempt.

## Acceptance and limits
A signed ACCEPTED is not delivery. One signed DELIVERED for two parts is partial. Original attempt remains the only binding. No sender is added, no live provider/KMS, no real delivery claims. Event signatures attest only a trusted provider's reported status, not human consumption. Retired/compromised keys may invalidate historical trust until reviewed.
