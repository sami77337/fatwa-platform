# FAST9 integrated local journey — 2026-11-15

## Goal and authority

Continue the owner's approved FAST9 implementation plan by composing existing work and closing the gap between the durable human-authored case journal and return-to-origin preparation. The deliverable is one reviewable development branch and Draft PR, with evidence for the changed behavior on its final code. This is not a production release or an accepted percentage of the 556-point scope.

Spec: the user's continuation instruction, repository AGENTS.md safety constraints, existing PRs #184, #189 and #193, and the existing approval/outbox contracts. D070 (visual polish deferred), D072 (U10 deferred), and the external ChatGPT V2 boundary remain unchanged.

## Architecture and stack

Python 3.13, pinned Django 5.2 dependencies, existing Arabic SSR workbench and disposable SQLite synthetic journals. Preserve the existing trusted approval-verifier boundary. Add a canonical read-only adapter from the journal to current delivery evidence; compose that adapter with the existing planner/outbox in synthetic integration tests. Expose useful preparation status in the local workbench without adding an approval or dispatch endpoint.

## Global Constraints

- Synthetic fixtures only; loopback/local development. No real requester data, live provider calls, publication, production permissions, production migration, merge to main, or deployment.
- A technical reviewer is not a MUFTI. Never issue a scholarly approval, invent a trusted verifier, or replace trusted signature/identity/revocation verification with a request boolean.
- Preserve exact source and authored text, revision identities, stale evidence rejection, separate roles, CSRF, no implicit retries, and ACCEPTED != DELIVERED.
- Never edit AGENTS.md, docs/coordination/**, the old Telegram bot, or Phase00 evidence.
- Use independent worktrees and disjoint file ownership for parallel work. Reuse unchanged historical test evidence; run meaningful affected and integration checks for this composition.
- Record limits honestly: NOT_DEPLOYED; GATES_HOLD. Do not claim PostgreSQL, live-browser, release acceptance or production results without running those checks.

## Task 1 — Compose the existing branches

Owner: coordinator. Merge PR184 internal draft handoff and PR189 lossless segmentation into the isolated branch based on PR193. Preserve histories and inspect conflicts. Relevant paths are the original branch diffs. Run their focused tests once after dependencies are available. No behavior redesign in this task.

## Task 2 — Add a combined CI contract

Owner: CI worktree. Create `.github/workflows/fast9-integrated-journey.yml`. One coherent job on the changed branch must exercise approval, planner, segmentation, outbox, recovery, integrity, author/reviewer handoff, operator, and the new journal bridge/preparation tests. Trigger on all production/test/template/settings files that can change that journey. Preserve existing workflows. Install pinned requirements on Python 3.13; use explicit synthetic/test settings and no production secrets. Keep the test command portable and validate its module list. Document the exact command in the task report. New modules can be added when the bridge/preparation tasks publish their contract.

## Task 3 — Canonical journal-to-return bridge

Owner: bridge worktree. Add `apps/fast9_case_source_join/return_handoff.py` and focused tests. Derive current delivery evidence from the verified durable journal, including latest human draft, exact source/reply hashes and blockers. Return a frozen candidate with exact body and stable evidence; refuse missing, stale or inconsistent evidence. No new identity authority or network operation. Integration tests must use an explicitly test-only approval verifier and demonstrate that journal changes invalidate stale preparation before reservation; test restart/deduplication and uncertain-delivery reconciliation using existing services where applicable. Final detailed function signatures follow the architecture audit and are recorded in the task brief before implementation.

## Task 4 — Local return-preparation page

Owner: coordinator, separate files from Task 3. Add an Arabic author/reviewer preparation view and template using the canonical bridge. Show precise blockers, exact authored text and explicit lossless split preview; keep all actions local and side-effect free. Link from the existing workbench pages. No approval, reservation, send, retry or delivered button. Preserve role isolation, CSRF and exact-text rendering. Meaningful client tests cover access, stale/bad form input, split consent and the connected review-to-preparation journey.

## Task 5 — Review and publish development evidence

Perform focused spec/quality reviews of each task, resolve material findings, run one independent whole-branch review, and verify the affected journey on the final code. Commit the code and an Arabic implementation/evidence note. Publish a new branch and Draft PR against the latest reviewed development base, without merging or deploying. Verify new CI if available. Any actual approval rejection is reported with its exact action/reason, without attempting a bypass.

Verification continuation: local sandboxed Chromium could not start because of socket/ptrace permissions. Add a bounded preparation/access/preview browser harness to the same CI job using the repository's existing sandboxed system-Chrome method. Keep the two verified service/client commands unchanged; upload a SHA-bound JSON receipt, fail rather than skip if the browser or an assertion fails, and record the actual hosted result before claiming browser acceptance. This does not add a production capability or weaken browser security.

## Review focus

The integration must bind the answer body and current source/reply evidence consistently across draft, plan, receipt and outbox. Do not mistake hash-chain integrity for authenticated human approval. Check stale handoff events, open clarification/correction blockers, separate author/reviewer/operator sessions, non-leaking error messages, exact Unicode segmentation, and workflow path coverage. Judge output by demonstrated behavior, not counts of files or CI jobs.
