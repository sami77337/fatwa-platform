# Case-source join implementation plan

Goal: a pure synthetic technical join, with no new source mapping or writes.
Base: 0769f66e93fdf710ca55e9e68e87430a93f14c40 (FAST8 #151).

The user's execution request is the approved specification. Execute inline;
only the final independent review uses a subagent. All files stay in this lane.

- [x] Write failing tests for pinned case packet, original occurrence, case-row
  SHA, opaque source ID, edition, work, catalog checksum and snapshot boundaries.
- [x] Implement `JoinRequest` and `join_case_source` in `services.py`. Select
  canonical existing synthetic cases, reuse FAST8 `_bind`, validate original
  byte slices, and use FAST8 navigation inside one caller-owned snapshot.
- [x] Add deterministic opt-in CLI and coherent fabricated catalog fixture.
  The older reading-trail fixture has different opaque source IDs; never repair
  or relabel it to make it join. No owner-archive acceptance is possible here.
- [x] Add guarded opt-in PostgreSQL tests via the existing Wave7TestRunner.
  No local preauthorized database identity was supplied: local PG is NOT_RUN.
- [x] Run offline new/affected tests, lint, independent read-only review.
  23 new / 160 new+affected passed; independent reviewer: no findings.
- Delivery: commit/push one draft PR to codex/20261026-fast8-integration-pc1;
  remote SHA and actual inherited CI results are reported in the PR/handoff.

Review focus: cross-case packets with identical pointers; opaque source IDs;
stale row/input/occurrence/catalog hashes; bool/float identities; failures on
snapshot exit withholding all successful evidence. Tests cover these classes.

Ruling: row_sha256 means SHA256 of packet.source.text UTF-8, matching the
existing CaseTriage.source_sha256. HeadingRecord has no original row-byte SHA;
do not invent one or imply the catalog checksum proves an archive was read.

Governance: Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.
