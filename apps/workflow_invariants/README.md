# Workflow invariant and replay engine

FAST5 already has working immutable draft transitions, pure intake/review
contracts, revision comparisons and a fixed eight-attempt rehearsal. This module
adds reusable ordered command replay and complete machine-readable evidence.
Only new lane-owned files are added; no existing endpoint, setting or dependency
is changed. The engine imports no Django or persistence service.

## Python API

```python
from apps.workflow_invariants.engine import make_event, replay, scenario

commands = scenario("rehearsal")
report = replay(commands)
event = make_event("intake-7", report["next_sequence"], "review", "start_review",
                   before=report["final"], event_id="synthetic-attempt-9")
commands["events"].append(event)
report = replay(commands)  # fresh local replay, not a persistent checkpoint
```

`replay(dict) -> dict` accepts an exact envelope with `schema` equal to
`fatwa.workflow-invariants.v1`, literal `synthetic_fixtures_only: true`, a fixed
`case_key` and up to 64 `events`. Empty logs return the initial state. Each event
has exactly `event_id`, `sequence`, `dimension`, `action`, `source_identity` and
`expected_state`. Use `make_event()` to pin a command to the full before-state
digest, revision, preparation/review states and fixed source identity. State
digests include all intake fields and all immutable history, including metadata,
Arabic, whitespace, reference fields and ordering. No normalization occurs.

The only dimensions are `preparation` and `review`. Actions are delegated to
`fatwa_drafts.domain.transition()` and `intake_workflow.contracts.next_review_status()`.
There are five actual preparation edges and four internal-review edges. Ready
preparation requires existing nonblank title/answer. The populated history fixture
provides these synthetic texts; callers cannot supply content or actor labels.
`REVIEWED_INTERNAL` is a technical contract label, not scholarly approval.

## Ordering, rejection and retry semantics

- Input order is authoritative; the engine never sorts or repairs a log.
- Sequence begins at 1. A structurally valid, source-pinned, in-order new event
  consumes its sequence and ID even if its before-state or domain action rejects.
- Malformed, wrong-source or out-of-order events are rejected without consuming
  a sequence or ID. Later valid events are still evaluated.
- The entire canonical event is bound to its ID with the existing pure intake
  idempotency contract. An exact retry returns the original accepted/rejected
  decision and `original_ordinal`; it makes no state change, even if later events
  have already advanced the state. Changed commands under an existing ID reject
  with `IDEMPOTENCY_CONFLICT`. Wrong-source commands reject before this check.
- Stale `expected_state` rejects atomically. Its full snapshot digest also catches
  review changes that did not increment a preparation revision.
- Invalid envelope/JSON, unsupported JSON types, excessive size/depth abort the
  request. Invalid individual event schemas produce per-event rejection evidence.
- A failed invariant aborts with `ReplayError`; no successful report is returned.

## Evidence and source limits

Every step carries the original event, its canonical SHA256, decision/reason,
complete before/after snapshots, both state hashes and exact JSON Pointer changed
paths. Reports retain original source text, byte offsets, full reference diagnostics,
payload and row-slice hashes. Row identity includes its case key and byte slice;
external IDs alone cannot identify the duplicate intake rows. The `history` case
uses serialized intake provenance and null byte offsets, explicitly labelled.
Verified synthetic reference bindings are checked against the existing intake
identity contract; this does not inspect or certify an owner archive.

`input_sha256` hashes canonical JSON commands. The CLI also reports
`input_bytes_sha256` for an input file/stdin so original whitespace is attributable.
Reports are detached JSON values: callers may mutate them without changing input,
fixed fixtures, other snapshots or later runs. Original gapped history IDs
`1, 2, 4, 7, 9, 11` remain intact; only appended revisions increment by one.
The existing revision history/comparison service checks each resulting history.

All inputs are bounded to 1,000,000 UTF-8 bytes, 64 attempts and 30 nested levels.
The service admits only JSON strings, booleans, null, lists, objects and bounded
integers; it never loads caller-supplied draft records. Fixture selectors and the
synthetic acknowledgement are development constraints, not authentication.

Historical owner transitions (including the 58), owner source archives and owner
acceptance evidence: **NOT_SUPPLIED**. No inference from synthetic fixtures.
Gate B **NOT_PASSED**; C/D/E **HOLD**; Phase01 **BLOCKED**;
**SCOPE_DEVIATION_HOLD**; **NOT_DEPLOYED**. No grants, scholarly decisions,
publishing, production writes, database migrations or persistent replay storage.
