# Multi-case requester tracking — synthetic-only design

## Goal
Track many independent requester cases and let a requester retrieve only their own minimal progress using a high-entropy, one-time-issued token. Never expose a user's question, answer, channel credential, identity, or case key.

## Approaches
- Make old `CASE_KEY`-bound journal multi-tenant immediately: rejected. Source journal and mufti policies are explicitly single-case fixtures; refactoring them without acceptance would risk ownership and stale-approval invariants.
- Expose the existing operator delivery report to requesters: rejected. It contains organizational metadata and broad operator scope, not a privacy-preserving per-requester capability.
- **Chosen:** additive multi-case tracking registry in owned synthetic PostgreSQL, independent of the older journal, with grant rotation, stage history and conservative derived delivery summaries. An explicitly disabled-by-default loopback requester view uses POST+CSRF to look up a token, never a query parameter.

## Trust model
- Only a server-provided trusted actor callback may register or advance a tracking case or rotate/revoke a tracking token. No requester endpoints create or modify case status.
- 256-bit secrets are generated server-side; PostgreSQL stores SHA-256 only. Lost token must be rotated by authorized operator.
- Tracking stages are operational notes, *not* MUFTI approval, delivery evidence or publication; those states can only be inferred conservatively from existing signed workflow and provider proofs.
- Token lookup exposes a coarse state and bounded part counts only. Failed/expired/unknown tokens return the same non-disclosing error.
- Read-only requester status is available only in explicit development settings on localhost, not in public or production URLs.

## Acceptance
Two cases never expose each other's metadata; token rotation revokes the old one; stale expected revision and invalid stage transitions fail closed; PostgreSQL event rows are immutable; `ACCEPTED` never equals `DELIVERED`; a legacy boolean-delivered provider record cannot count as verified delivery.
