# Mufti Review Cycle Implementation Plan

> Execute inline with superpowers:executing-plans and regression-first verification. Existing owner authorization covers isolated development branches and Draft PRs only.

**Goal:** close the author -> human Mufti review -> signed receipt staging loop without confusing a review decision with a cryptographic approval or sending.
**Base:** PR205 at 038a4a7b00dc897797446a730c3d30e7ff35e6ef; tree 524a585163ce346150117e560c52bc582c3e0db7.
**Architecture:** new isolated Django app apps/mufti_review, enabled only in its own synthetic PostgreSQL test/review profiles. Reuse the exact author request, source journal, Ed25519 verifier and PostgreSQL staging from PR205/204.
**Tech stack:** existing Django 5.2 / Python 3.13 / PostgreSQL 17 and 18. No new dependencies.

## Design / alternatives
Selected: persist request identities and human review decisions; an explicitly configured server-side identity provider authenticates and re-resolves the MUFTI actor. Browser roles/tokens never become signing authority. READY_FOR_SIGNATURE is a human review result, not APPROVE_RETURN_TO_ORIGIN, and creates no queue intent. A later external receipt must match the same actor, request, current source and decision chronology.
Rejected: embed a private signing key in the web application; treat the existing reviewer role as MUFTI; create a second queue. The existing author-only profile is preserved for its synthetic tests, while the new combined profile requires the review decision before staging.

## Global constraints
- No live identity provider is invented or activated; default identity provider and verifier are None.
- No signing key in application paths. No sender, real data, main merge, deployment or gate changes.
- Review requests and decisions are immutable. One final decision per exact request; a corrected human draft creates a new request identity. No silent override of a prior decision.
- Decisions: RETURN_FOR_CHANGES / DECLINED / READY_FOR_SIGNATURE. Negative decisions require a meaningful note. Readiness never authorizes sending.
- Exact journal text and source files remain unchanged. Request history stores hashes and bounded notes, not answer bodies or requester credentials.
- Role, active state, case scope, authentication epoch and expiry are resolved server-side on every access and again inside decision/staging transactions.
- Explicit native POST, CSRF, browser-bound snapshot confirmation, strict bounded input, no-store, loopback-only profile.
- Source SQLite and queue PostgreSQL are not a distributed transaction. Recheck before decisions, after locks and before existing queue reservation; do not claim global exactly-once.

## Implementation tasks
- [ ] T1: add expected-failure service/auth tests and a strict exact-revision PostgreSQL 17/18 workflow.
- [ ] T2: add immutable ReviewRequest and ReviewDecision models, migration, scoped identity adapter and atomic submission/decision/staging services.
- [ ] T3: add author status/history and a separate MUFTI desk with native authentication, explicit human actions and a non-signing decision export.
- [ ] T4: prove stale evidence, revoked/inactive/out-of-scope actors, wrong signer, receipt predating the decision, repeat submissions, concurrent opposing decisions and unchanged original journal.
- [ ] T5: real Chrome author -> reviewer -> external synthetic signer -> staged-not-sent workflow, including a return-for-changes round trip, accessibility and privacy evidence.
- [ ] T6: final diff review, exact-SHA artifacts and honest readiness/progress report.

## Review focus
No READY result creates an ApprovalClaim; rejection cannot be bypassed by a preexisting signature; the signed approver must be the human who reviewed the current request; changed requests remain distinguishable in history; the author role must never open the Mufti action endpoints; a recreated browser cookie alone must not authenticate.

## Progress accounting
Baseline is approximately 42% +/-5 points, not a weighted acceptance score. Update only a cautious overall estimate after verified functionality; do not turn an additional test or PR into an automatic percentage point.
