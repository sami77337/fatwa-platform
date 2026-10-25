# Synthetic case review packet

Goal: a navigable Arabic read-only packet for each existing fixed synthetic case.
The user's FAST3 request is the spec and authorizes implementation now.

Architecture: compose existing FAST2 workbench cases with Wave3 history,
comparison and snapshot audit services. Use `?packet=html|json|print` on the
existing guarded detail URL; do not change shared routes or load persisted data.
Only the three assigned workbench directories may change.

## Tasks

- [x] Add failing packet tests for exact intake/source identity, Unicode/CRLF,
  rejected/duplicate cases, immutable snapshots, reverse/equal comparisons,
  technical reference scope, unresolved issues, deterministic bounded export.
- [x] Implement `build_packet(case, batch, revision, before, after)` and a strict
  bounded UTF-8 serializer in `apps/editorial_workbench/packets.py`.
- [x] Add failing HTTP tests for navigation, selected IDs, JSON/print parity,
  escaping, invalid/duplicate queries, guards, methods, no persisted reads.
- [x] Connect packet modes in `views.py`; add owned packet template, links and
  print CSS. Preserve existing filters, comparison selection and recovery.
- [x] Run focused new and affected workbench tests, lint, formatting and system
  checks; obtain one independent final review; fix substantive findings.
- [ ] Commit/push this development branch and open one draft PR against verified
  `codex/20261024-fast2-integration` (`e64ebc0d219f975eb7be96042a4e8761b1a0e6e9`).

Review focus: a duplicate external ID must not join histories; absent persisted
events must remain unknown rather than an empty proven history; diagnostic scope
must not follow selected historical revisions; malformed/unbounded UTF-8 must
fail closed without truncation; source serialization must not claim original
file slices or invented offsets. Existing limits and all product holds remain.

Baseline: explicit four workbench modules passed 33 tests. Package-only discovery
failed because the top-level tests namespace has no `__file__`; explicit module
labels work. No PostgreSQL or owner-source acceptance is claimed.

Verification: 13 new tests plus 33 affected tests pass. Independent final review
reran the original 45-test set; its empty-ID builder finding was corrected with a
failing-first regression and the full focused 46-test run. Defaults apply only to
`None`, preserving strict exact selection. Browser QA verified Enter navigation,
six snapshots, print expansion and desktop/mobile overflow. No deferred findings.
