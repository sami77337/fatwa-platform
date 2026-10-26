# Prepared-to-review bridge implementation plan

**Goal:** Project existing synthetic prepared rows through existing preparation and
internal review contracts with exact source and before-state checks, without persistence.

**Architecture:** Reuse `build_prepared_workbench`, domain `transition`,
`next_review_status`, revision history validation, and workflow invariant snapshot/token
helpers. The prepared adapter's C2 identity is not a complete Wave7 verified identity:
report this join as NOT_CONNECTED. Preparation and review remain independent dimensions.
No inferred readiness, authority, source byte offsets, timestamps or missing transitions.

**Tech stack:** Python 3.13, standard-library unittest; no new dependencies or UI routes.
**Spec:** Owner's FAST8 prepared-review lane request and base
`92fa517ecdefe3f1a92a1ab145ff55943474df44` / Draft PR #134.

## Constraints and design choice

Only the three owned fast8_prepared_review directories may change. Use the existing
fixed prepared fixture provider, never arbitrary source records or archives. A separate
adapter is necessary because workflow_invariants selects only legacy cases, and its
source_identity assumes fields absent from prepared reference diagnostics. Do not fork
the replay engine or patch its private selector. Instead provide a bounded sequential
projection with explicit expected source/state on every attempt and no retry ledger.
An identical accepted command becomes stale when submitted again.

User explicitly requested autonomous execution, one isolated Draft PR to
`codex/20261026-fast7-ci-integration-pc1`, and only new/directly affected tests.
Plan, evidence and documentation stay in owned directories; shared skill workspace
scripts and broad historical suite reruns do not apply to this lane's scope.

## Task 1: pure bridge, scenario and diagnostics

- [x] Write tests for complete row identity, source fingerprint, revision/state tokens,
  real allowed/invalid transitions, rejected/missing drafts and unconnected joins.
- [x] Run new tests red, then implement `inspect_case`, `project`, `scenario` in
  `apps/fast8_prepared_review/services.py`, reusing domain services.
- [x] Add `python -B -m tools.fast8_prepared_review --synthetic-fixtures-only` with
  deterministic JSON before/after evidence; test command output and missing ack.
- [x] Run new tests and directly affected pure service tests; lint owned files if
  the existing tooling is available. No browser route is added or changed.
- [ ] Obtain one independent review, fix substantive findings with regression tests,
  record results, commit/push isolated branch, open one Draft PR and verify remote/CI.

## Review focus

1. Duplicate external IDs in distinct batches must never alias a source identity.
2. Bool/int and other JSON type aliases must not bypass revision/ordinal checks.
3. Missing or stale fields and arbitrary cross-dimension joins fail closed.
4. Arabic, CRLF, combining marks, references and all previous revisions stay exact.
5. Accepted review labels never imply reference verification, human approval or
   preparation readiness; denied attempts retain identical before/after snapshots.

## Progress

Inspected all three requested domains and actual prepared fixtures. Existing fixture
set: 11 rows in CSV/JSON/JSONL plus one malformed batch; four existing receipt drafts.
No owner archives supplied or accessed. Implementation complete. Initial validation:
19 new / 63 total directly affected tests passed without skips. Independent review
completed with one P2 excessive allocation finding; fixed by streaming bounded JSON,
with one new red-to-green regression. Final local validation is recorded in VALIDATION.md.
