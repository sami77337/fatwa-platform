# Exact reviewed edition scheduling — original point 138

Default-off synthetic development functionality for SPEC-U07-023 / D-035. A human chooses the reviewed edition, WEBSITE_PREVIEW destination and a future time (displayed in Asia/Amman, stored as UTC). This is not owner acceptance or production activation.

A schedule seals its exact approved answer, evidence and case revision, independent review, edition digest, actor/provider epoch, destination and time. The idempotency key binds the whole choice. Cancellation appends a terminal result without changing the source or schedule. At most one pending schedule per edition is allowed under the canonical case lock.

`run_due_publications --limit 20` is a bounded one-shot worker. An external development scheduler may invoke it; no production scheduler is installed. Execution reloads the configured current identity directory and explicit scheduling and publication authorities, rechecks current source/citation rights and exact latest reviewed edition, and uses the existing publication approval service. It cannot publish early or select a newer edition silently. A changed source, actor epoch or permission yields a terminal HOLD. Approval and its PUBLISHED outcome commit atomically. Concurrent/replayed execution reuses the terminal outcome. No requester delivery is performed.

## Controls and persistence

`FATWA_PUBLICATION_SCHEDULES_ENABLED=False` and `FATWA_PUBLICATION_SCHEDULES_AUTHORITY=None` remain the defaults. Current authorities expose pure projection epochs; the final render/commit checks them again. The native case tab uses CSRF POST forms with exact fields and binds the current authenticated actor. It displays scheduling, cancellation, outcome and reason history without editing approved answer text.

Two append-only tables (`PublicationSchedule`, `ScheduleOutcome`) are protected by `ps_history_guard()` and two triggers. A PUBLISHED row requires the exact existing publication APPROVE action and due time. Every other outcome has no publication action. The recovery helper populates real cancelled and published schedules; restored readers recreate explicit current trust, prove three denials and a subsequent positive read, and leave schedules and canonical source/history unchanged.

## Evidence boundary

`apps.publication_schedules.tests` has ten service/native/database tests, including real due execution through a fresh connection, the actual worker command, same-key replay, no early publication, cancellation, changed facts/version, current authority/epoch revocation and a late callback that rolls back the publication. All ten passed on PostgreSQL17 and18. `apps.publication_schedules.test_recovery` adds nonempty restored-history/current-trust verification; the integrated encrypted drill remains separately required.

The protected journey is `apps.publication_schedules.browser_tests.PublicationScheduleBrowserTests.test_native_exact_future_schedule_cancel_due_publication_and_changed_authority_hold`. It drives real native forms, cancellation and early refusal, advances only the explicit test clock, then drives the real due-worker form and reads the exact anonymous public edition. A later revoked grant produces HOLD with no additional APPROVE action. Screenshots at320/1280 and two traces are retained at `.local/qa/functional-continuation/publication-schedules-browser/`. No protected browser PASS is claimed before the exact hosted checkout executes it.

GateB NOT_PASSED; GatesC/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
