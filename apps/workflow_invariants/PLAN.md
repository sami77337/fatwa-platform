# FAST6 workflow invariant replay

User specification: FAST6 lane 1, base `0eef6b29943364dddae35a193b356ab79a2e2b5e`.
Implement now; all new files remain in the three lane-owned directories.

Use a pure Python replay service over fixed FAST5 cases and existing transition,
intake idempotency, revision history and comparison contracts. No ORM, endpoints,
arbitrary draft content, actor input, writes, or network. CLI reads bounded JSON
event commands and emits deterministic UTF-8 JSON to stdout. Existing source
text and reference identity remain exact, with source and event digests.

1. Write failing unittest coverage for deterministic replay, source pinning,
   rejection atomicity, idempotency conflicts, out-of-order commands and all
   actual preparation/review edges. Implement engine and exact snapshots.
2. Add bounded CLI, fixed synthetic scenarios, malformed-input tests and usage.
3. Run focused new and directly affected suites on Python 3.13; run lint.
4. One independent final review; fix actionable findings with regression tests.
5. Commit/push isolated branch, create one draft PR to FAST5 integration branch,
   verify remote SHA and actual CI; report unavailable evidence explicitly.

Review focus: duplicate keys and non-JSON types; bool/integer identity confusion;
rejected-event retries; stale review state without a revision change; source
identity collisions for duplicate intake rows; original revision gaps.

Historical owner transitions: NOT_SUPPLIED. Gate B NOT_PASSED, C/D/E HOLD,
Phase01 BLOCKED, SCOPE_DEVIATION_HOLD, NOT_DEPLOYED.

Implementation and focused verification completed: 22 new + 70 pure contract +
17 existing adapter tests passed. One independent final review identified one
history error translation defect; regression tests reproduced it and passed after
the fix. Full commands, fixture hashes and evidence limits are in VALIDATION.md.
