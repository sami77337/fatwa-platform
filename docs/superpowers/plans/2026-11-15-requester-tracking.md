# Multi-case requester tracking — implementation plan

> REQUIRED SUB-SKILL: superpowers:executing-plans, test-driven-development.

**Goal:** create independently scoped requester cases and a token-based, minimal-status self-service reader in synthetic PostgreSQL.
**Architecture:** Add tracking models under existing queue app; do not rewrite the original one-case journal. Separate private operator service from read-only requester view.
**Stack:** Python 3.13, Django 5.2, PostgreSQL 17/18, native template + CSRF.
**Spec:** docs/superpowers/specs/2026-11-15-requester-tracking-design.md.

## Constraints
- Base PR207 SHA 27d790fe67970f5e8d94dfc280233228dff3aa34.
- No real requester records, sender, production URL, auto-approval or deployment.
- Do not change AGENTS.md, docs/coordination or main.
- Deny defaults and fail-closed owned-synthetic guard.

## Tasks
- [ ] 1. RED: multi-case registry tests for unique 256-bit token, token hash only, identity/authorization and two-case isolation.
- [ ] 2. GREEN: tracking models/migration and service. Tests: rotation, expiry, immutable history, stale revision, permissible stages.
- [ ] 3. RED/GREEN: conservative read projection from existing queue. Tests: ACCEPTED is in-progress; legacy DELIVERED is unverified; other case not leaked.
- [ ] 4. Add opt-in local requester portal, POST-only token verification, CSRF, minimal Arabic RTL view. Test unauthorized, method, privacy, no-store, mobile.
- [ ] 5. Run PG17/18 + targeted browser acceptance, capture exact SHA/test counts. Open Draft PR, avoid merging/deploying. Report realistic % not PR count.
