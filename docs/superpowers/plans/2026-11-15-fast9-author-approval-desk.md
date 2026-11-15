# Author Approval Desk Implementation Plan

> Execute inline using superpowers:executing-plans, test-first and on the isolated development branch only.

**Goal:** connect the existing human-authored case journal and its technical review to signed MUFTI approval intake and PostgreSQL staging through an explicit author workflow.
**Base:** PR204, f2f1358aad1b977948c63e37b967c215f394ae44.
**Architecture:** reuse read_return_candidate/read_current_evidence, prepare_text_return and commit_signed_approved_plan. Add a journal handoff service and a separate default-off loopback author desk. Never issue approval or contact a sender.
**Stack:** existing Django 5.2, Python 3.13, PostgreSQL 17/18, Ed25519 verification; no dependency changes.

## Design and alternatives
Selected: export a precise human-review request, then import a receipt signed outside the application using a server-supplied trusted verifier. An in-browser private-key signer would blur the MUFTI trust boundary; a new queue would duplicate PR204. Neither is implemented.
The author may stage an already signed receipt but cannot create a MUFTI decision. Technical review is never religious approval. The supplied user authorization permits development branches and Draft PRs, not main merges or production activation.

## Constraints
- No real cases, signing keys, external identity provider, sender, delivery or publication.
- Preserve original journal bytes. All source changes invalidate the prior request.
- Fixed server-side channel capabilities; users cannot choose an issuer/key/target from browser input.
- Scope comes from server settings, not URL filenames; no arbitrary paths.
- Explicit human split choice, exact Unicode/CRLF, strict bounded JSON with duplicate-key rejection.
- CSRF and browser-bound confirmation; author role only for staging; no-store and loopback-only routes.
- Preserve prior migrations and public URLs.

## Tasks
- [ ] 1. Add failing real-journal/real-PostgreSQL service and HTTP regression tests and observe RED.
- [ ] 2. Implement deterministic approval-request export, strict signed-response decode, current journal reconstruction and atomic PostgreSQL staging.
- [ ] 3. Add default-off Arabic author desk, native author login, request download and explicit receipt import with CSRF/current-snapshot confirmation.
- [ ] 4. Test stale source/draft, open clarification, key revocation, cross-case receipt, duplicate JSON keys, wrong role, wrong browser confirmation, retries and journal immutability.
- [ ] 5. Test the complete native browser workflow; save exact-SHA evidence, screenshots and counts; update review notes.

## Review focus
A signed old request must fail after source/draft changes. A valid browser login must not substitute for MUFTI identity. Request export must not create claims. Re-import of the same exact signed receipt must not create another plan. GET/HEAD must not mutate anything. No state should be described as sent merely because it is staged.

## Progress accounting
The inherited overall estimate is about 40%, not a weighted acceptance score. Report a cautious revised estimate and the achieved scope, not an automatic +15 points. This desk does not close live identity/channel or production acceptance gates.
