# FAST9 Signed Provider Evidence v1 — Design and Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task, test-first.

**Goal:** verify provider-signed, per-part channel outcomes and persist auditable proof, while never sending or marking an answer delivered from ACCEPTED alone.

**Architecture:** reuse the existing owned PostgreSQL queue, immutable attempts, and locked audit chain. A separate Ed25519 verifier validates provider event claims; an adapter binds them to the original leased intent and its planned part before calling the existing atomic receipt writer. Optional signed evidence is retained in the SAME transaction via a new append-only table. This is test-only, provider-neutral and disabled from all public routes.

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL 17/18, cryptography Ed25519.

**Spec:** docs/superpowers/specs/2026-11-15-signed-provider-evidence-design.md

## Global Constraints
- Base PR206 SHA 84d1e2b26c41e2cb33d7ec1a0c1813d8687dd34e.
- Only synthetic records; no channel network access, no sender, no real identity or requester data.
- Do not edit main, AGENTS.md, coordination, phase00, or production settings.
- No silent retry of UNKNOWN, no publishing, no real user communications.
- Signed provider receipt is **evidence of the provider's assertion**, not a guarantee of human consumption. ACCEPTED is never DELIVERED.
- Existing bool-callback receipt path is internal synthetic test API; never expose it as public provider proof acceptance.
- Fail closed on unknown keys, expired receipts, wrong part/attempt, bad source, and store failure.
- Keep PR206 intact, open a draft PR against its branch, and preserve older tests.

## Review Focus
- Signature is not bound to the exact original lease token hash / part -> must fail.
- Fake DELIVERED from ACCEPTED -> must not complete.
- Crash between receipt insert and proof persistence -> must roll back as one.
- Expired or unavailable provider trust -> reject without mutation.
- Late proof after lease quarantine -> accept verified historical attempt without requeue.

### Task 1: RED evidence and trust envelope
**Files:** tests/delivery_queue/test_signed_provider_receipts.py; apps/delivery_queue/signed_provider_receipts.py
- [ ] Add contract tests for signed status, issuer/audience/provider, key retirement and exact part.
- [ ] Run PG 17/18 CI, record expected failures because signed adapter is missing.
- [ ] Implement canonical Ed25519 event payload, explicit keys, UTC bounded clock, and fail-closed key callback.
- [ ] Rerun tests.

### Task 2: Atomic persistence and audit
**Files:** apps/delivery_queue/models.py, migrations/0004_provider_signature_evidence.py, services.py
- [ ] Write tests for proof storage, DB immutable triggers, exact event replay, and crash rollback.
- [ ] Add ProviderSignatureEvidence model and migration; require empty receipt history for existing DB migration.
- [ ] Extend internal record_receipt with optional strict signed_evidence; persist in the SAME atomic transaction as state and audit.
- [ ] Verify stored proof with trusted key and receipt/intent/attempt bindings, using original recorded_at to validate historical signatures.
- [ ] Run new and inherited queue suites.

### Task 3: Composite delivery acceptance
**Files:** tests/delivery_queue/test_signed_provider_receipts.py, .github/workflows/fast9-postgres-delivery-queue.yml
- [ ] Validate two-part plan only complete with two separate signed DELIVERED proofs.
- [ ] Validate ACCEPTED→DELIVERED, rollback, wrong lease, after-quarantine receipt.
- [ ] Run CI on PostgreSQL17/18, verify exact tested SHA and all affected workflow states.
- [ ] Perform independent diff review and update Draft PR with PASS/FAIL facts.

**Non-goals:** actual channel connector, automatic issuer of receipts, operator approval based on pasted text, production DB migration, live revocation service, main merge, deployment.

## Task 4: Verified provider-reported multipart audit
- [x] RED tests for signed-vs-unsigned complete plan, revoked keys, and read-only audit.
- [x] Conservative all-parts audit within one locked PostgreSQL head snapshot.
- [ ] GREEN PG17/18 and check exact head SHA.
- [ ] Update Draft PR and evidence report, no merge/deploy.
