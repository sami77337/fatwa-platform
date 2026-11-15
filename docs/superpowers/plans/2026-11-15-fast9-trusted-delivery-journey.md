# FAST9 Trusted Delivery Journey Implementation Plan

> Use superpowers:executing-plans in this session.

**Goal:** connect signed human approvals, exact source/answer evidence and PostgreSQL delivery while preserving uncertainty and least disclosure.
**Base:** PR201 ce55b5c672599fcdd1c11aa4ebff8f3aeede25b3.
**Architecture:** additive synthetic-only services on the existing queue; no new sender, public routes, production activation or changes to main.
**Tech stack:** existing Python 3.13, Django 5.2, PostgreSQL 17/18, Ed25519 verifier and lossless text planner.

## Design / alternatives
A second independent queue would duplicate PR201. Production activation would violate unresolved gates. Selected: a trusted gateway on the existing queue, durable signed metadata, post-lock revalidation and an opt-in read-only operator report.

## Global constraints
- Preserve all prior functionality and files. Do not edit AGENTS.md, docs/coordination, production settings or source originals.
- Use existing Wave7 owned synthetic database guard before transactions.
- Store signed metadata, never answer text, signing keys or clear worker tokens.
- Unknown delivery outcomes are not automatically retried.
- No external identity provider, KMS, messaging API, production migration, merge or deployment.

## Tasks and acceptance
- [ ] T1: add regression tests for production/default-off boundaries, malformed/boolean inputs, expired claims, post-lock approval checks, accepted-state summaries and wrong-token replay. Observe RED on PostgreSQL.
- [ ] T2: harden services, add immutable signed_context migration and preserve explicit synthetic fixture API. Run the original queue suite and regressions.
- [ ] T3: connect signed receipts to freshly reconstructed plans and current evidence at staging and worker reservation. Test generated Ed25519 keys, tampering, revocation and stale source evidence.
- [ ] T4: bounded scoped operator report/JSON export with no-store headers and existing training operator cookie verification. Test unauthorized cases, GET/HEAD and mutation denial.
- [ ] T5: exact-revision evidence runner, PostgreSQL 17/18 checks and full diff review. Update Draft PR and readiness report without treating CI as product acceptance.

## Progress accounting
Baseline is approximately 40%, not a weighted 556-item acceptance score. Requested +15 percentage points is a target, not an automatic increment. Record accepted criteria and outstanding gates before estimating progress.
