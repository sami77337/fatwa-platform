# Manual case assignment and Mufti workload

This optional synthetic module implements coordination on the existing canonical
case. It addresses owner points **56–65 and 437–438**, with the detailed contracts
in `SPEC-U02-002`, `SPEC-U02-005`, `SPEC-U02-035`, and `SPEC-U14-012`. These mappings
identify the bounded functions below; they are not an acceptance or percentage claim.

## Working functions

- A currently authorized Mufti can claim an unassigned case and release their own
  primary assignment back to the shared queue. Concurrent claims have one winner;
  the other receives a conflict with refreshed current assignment information.
- The primary Mufti may transfer responsibility, add a contributor or add a
  reviewer **only** through an explicitly configured server candidate policy.
  Every candidate must independently resolve as an active MUFTI already scoped to
  this exact case. An arbitrary subject ID or a browser-supplied role is insufficient.
- A scoped Mufti can record or withdraw their own contribution/review participation.
  A primary Mufti can remove a participant. These are coordination labels: they
  grant no case access and confer no additional scholarly approval authority.
- The existing inbox now offers my cases/participations, unassigned shared cases,
  facts added after the latest answer, saved unapproved drafts, reviewable answers,
  and approved answers. Search and state filtering compose with these views.
  Workload counts remain based on the whole current authorized scope. An approved
  view with assignments enabled orders newest/oldest by the actual approval time.
- Native case forms show the primary Mufti, contributors/reviewers and the immutable
  assignment history. The same panel appears in the connected Mufti overview.

The new-followup view means evidence newer than the latest authored answer's
basis, or followups to a case with no answer. Opening the page does not mark facts
as read, and no claim of human evidence acknowledgement is made. Saved drafts are
actual existing unapproved answer revisions, including returned or stale drafts.

## Authority, concurrency, and persistence

`FATWA_CASE_ASSIGNMENTS_ENABLED` defaults to `False`. Register `apps.case_assignments`
in an explicitly synthetic profile before enabling it. Existing casework database,
loopback, browser-cookie, CSRF, field allowlist and maintenance admission controls apply.

`FATWA_CASE_ASSIGNMENT_CANDIDATES` is optional. Its trusted server callback has the
signature `(actor_subject_id, case_ref) -> list[str] | tuple[str, ...]`. It returns
at most 16 distinct subject IDs from the currently configured
`FATWA_CASEWORK_IDENTITY_PROVIDER`; the service independently validates their role,
scope, active state, validity and epoch before and after an assignment write. With
no callback, only self-coordination is available. The callback must not use client
assertions as authority. No identities are enumerated or automatically granted scope.

`AssignmentEvent` is an append-only hash-chained journal. Each event records its
actor/provider/epoch, target, action, canonical case/evidence pins, assignment
sequence and database transaction. PostgreSQL enforces immutable rows, consecutive
versions, hash linkage, action transitions, one primary, and the 16-participant
bound. The canonical case lock serializes competing writers. The service separately
checks current identity, scope and optimistic assignment version. An exact retry of
the immediately preceding accepted command is idempotent; intervening metadata or
case changes conflict. The journal is bounded to 256 events per synthetic case.

Queue annotation holds canonical locks for the complete batch in a fixed case-ID
order and verifies the original identity's scope, epoch and provider again before
returning. Removing an earlier case from scope during a later row closes the whole
projection. A refreshed identity validity deadline alone is not treated as revocation.

Assignments do not change `Case.revision`, `EvidenceVersion`, answer revisions,
approval, delivery or publication. Assignment is not an exclusive edit lock. Other
already-authorized Muftis keep their existing access. There is no organizer privilege,
automatic specialty routing, forced takeover of another primary, external message,
or requester/public assignment projection. Provider changes fail closed against
the historical namespace. Historical participant names are identifiers recorded by
the trusted directory, not a claim that every past participant remains active now.

## Integration and verification

The team workspace directly handles `assignment_claim`, `assignment_release`,
`assignment_transfer`, `assignment_contributor`, `assignment_reviewer`, and
`assignment_remove`. No new URL, cookie, browser capability or dispatcher is needed.
Existing filter forms without `sort` or `inbox` continue to use `newest` and `all`;
empty, unknown or duplicate supplied values remain invalid.

The recovery inventory must include `case_assignments_assignmentevent`, its sequence,
and `ca_assignment_guard()`/trigger. Every public service uses existing maintenance
admission, including reads that lock the canonical case for consistent projection.

Run PostgreSQL verification with the repository's isolated runner, using
`--settings apps.case_assignments.settings` and tests:

```text
apps.case_assignments.tests
apps.case_assignments.review_tests
apps.team_workspace.tests
tests.casework.test_v7_workspace
```

Protected browser target:

```text
apps.case_assignments.browser_tests.AssignmentBrowserTests.test_claim_mine_shared_release_on_mobile_and_desktop
```

Browser evidence writes `.local/qa/case-assignments/browser/` only after an actual
protected-browser journey. HTTP/service results do not imply browser success.

**NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.** No main merge, live data,
production migration, automatic assignment or new U03 policy grant.
