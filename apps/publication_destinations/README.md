# Independent publication destination histories

This recovered continuation implements original owner points **136** (a separate
publication record for each destination) and **137** (different destination
copies while preserving the original). It does not implement external publishing
in point135 or a deliverable public URL in point120. The existing independent
publication edition remains the exact human-reviewed content source.

## Behavior

Each synthetic case can have a `WEBSITE` record and a `TELEGRAM_CHANNEL` record.
These are independently versioned records, not aliases for the globally latest
publication edition. An editor selects the exact ID and SHA-256 of an already
reviewed and approved edition for one destination. The stored version pins the
source answer, scientific decision, reference snapshot, publication review,
approval, destination capabilities, and complete serialized publication plan.
Different destinations may deliberately select different approved editions of
the same current answer.

A separate reviewer reviews that destination version. An independently
authorized publisher approves it and prepares its exact plan. The preparer must
be independent of the selector, destination reviewer and scientific approver.
No role label supplies any of these action grants implicitly. Preparation lasts
at most15 minutes and never outlives the current identities or observed grants.

The desk accepts a typed Ed25519-signed outcome from the configured **offline
simulator**. A valid signature pins the exact record, version, destination,
source, capability profile, plan and preparation. The states distinguish
`ACCEPTED`, `SIMULATED_PUBLISHED`, and `FAILED`; accepted never means published.
The current published field is explicitly a simulated result and always carries
`external_publication_verified=false`. A browser cannot supply a trusted public
key, destination profile, verified flag or public URL.

Correction creates a new immutable version. A pending or failed correction does
not replace the last successful version. A successful correction replaces it
for that destination only. Withdrawing the latest successfully published
version leaves no current version and does not resurrect an older one. Prior
successes, failures, notes and actors remain in append-only history. Withdrawing
an exact source edition makes its destination copies unavailable while an
independent destination using another valid source remains available.

No function sends network requests, creates a delivery intent, edits an answer,
changes a scientific decision, rewrites publication editions, or changes the
existing public library's latest-edition rule. Actual external publishing needs
a separately reviewed adapter, real provider authority and availability proof;
none is asserted by this app.

## Integration and access

Register `apps.publication_destinations` in the shared campaign and preserve these
closed defaults:

```python
FATWA_PUBLICATION_DESTINATIONS_ENABLED = False
FATWA_PUBLICATION_DESTINATIONS_AUTHORITY = None
FATWA_PUBLICATION_DESTINATION_PROFILES = None
FATWA_PUBLICATION_DESTINATIONS_PROVIDER_VERIFIER = None
```

The existing `FATWA_EXPERIMENTAL_PUBLICATION_ENABLED`, publication authority,
current staff directory and exact source rights are independently required.
Production execution is refused. `DestinationAuthority` supplies finite grants
for `READ`, `SELECT`, `REVIEW`, `APPROVE`, `PREPARE`, `OBSERVE` and `WITHDRAW`, scoped
to the exact case, destination, resource ID and digest. Grants require explicit
aware deadlines within an hour. Every configured authority and directory must
provide a pure revision snapshot; an opaque policy callback cannot stand in for
that final consistency check.

The native case menu opens the desk with a POST to `/casework/staff/` carrying
`action=pd_open` and the canonical `case_ref`. The shared dispatcher sends the
four actions in `views.ACTIONS` (`pd_open`, `pd_select`, `pd_decide`,
`pd_provider_event`) to `views.workspace`. Subsequent forms contain exact case
revision, evidence version, destination version/event count, unique request key,
an explicit note and confirmation. CSRF, current authentication, loopback guards,
private/no-store responses, exact field allowlists and bounded body/form limits
remain those of the shared staff composition. The isolated URL wrapper in
`urls.py` exists for focused tests; it is not the final integration proof.

All writes and complete template rendering hold the canonical case boundary and
destination history lock. Before returning, the code rechecks current source
rights, identities, action grants, source/answer/publication data, policy/key
snapshots and deadlines. A late change discards the response and rolls back a
new destination append. Current source withdrawal, identity change, grant
revocation, trust-key revocation or capability revision cannot preserve stale
availability merely because a historical approval remains stored.

## Persistence and verification

The app adds three tables:

- `publication_destinations_destinationrecord`: one stable record per case and
  destination.
- `publication_destinations_destinationversion`: at most64 sealed versions per
  record, each bound to its exact original source and previous version digest.
- `publication_destinations_destinationevent`: at most6 chained events per
  version; one occurrence per action, with unique request and provider-event
  keys, finite preparation, typed provider evidence and legal state transitions.

PostgreSQL triggers reject updates/deletes and resealed inserts that change
source pins, plans, independent participants, sequence or transition rules.
Canonical case locks serialize compare-and-set writes; an exact replay returns
the original result, while reuse of its key with different input is rejected.

Focused tests in `tests.py` cover two independent destinations, different exact
copies, signed accepted/success/failure, failed corrections, withdrawal isolation,
source/right/identity/key revocation, stale versions, concurrent writers,
idempotency, forged signatures and direct SQL mutation, and actual authenticated
CSRF-protected forms. `test_recovery.py` exercises fresh-connection read-only
recovery of two records, three versions and13 events, retaining nonempty original
delivery history and nine explicit current-trust denials followed by a positive
read. `recovery_support.TABLES`, `FUNCTIONS` and `TRIGGERS` are the aggregate
encrypted-recovery inventory; these local checks do not alone certify an
encrypted restore.

`PublicationDestinationsBrowserTests` uses the real shared case menu, independent
authenticated browser contexts and native forms. It requires protected Chromium,
320px and1280px RTL screenshots, forged-outcome rejection, correction/withdrawal
and current-rights denial. It writes the actual proof to
`.local/qa/functional-continuation/publication-destinations-browser/result.json`.
Final requirement credit requires that native journey and the integrated
encrypted recovery to pass on the same final source tree, on PostgreSQL17 and18.

Gate B remains `NOT_PASSED`; Gates C/D/E `HOLD`; Phase01 `BLOCKED`;
`NOT_DEPLOYED`. No source inventory, acceptance policy or final design is changed.
