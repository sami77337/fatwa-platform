# Human priority and administrative assignment — original point 96

This feature implements the original organizer requirement “يمكنه إدارة الأولوية
والتعيين.” It adds native, CSRF-protected forms to the existing operational queue.
The actual ORGANIZER / ORGANIZER_ADMIN / MUFTI subject and role are retained in
each event. It never changes an identity to MUFTI to obtain scholarly authority.

## Activation contract

- `FATWA_OPERATIONAL_COORDINATION_ENABLED=False` by default; both the operational
  workspace and case assignments must also be enabled literally.
- The existing `OperationalAuthority` must explicitly grant READ_CASE and
  READ_COORDINATION for the case. Writes separately require SET_PRIMARY,
  CLEAR_PRIMARY or SET_PRIORITY on an exact CASE_COORDINATION resource.
- `FATWA_CASE_ASSIGNMENT_CANDIDATES` is a trusted callable `(subject_id, case_ref)`
  returning at most 64 distinct subject identifiers and a pure `projection_epoch()`.
  The new operational path rejects unversioned callbacks. The existing Mufti
  assignment path retains its existing compatibility contract.
- `FATWA_OPERATIONAL_PRIORITY_POLICY=None` by default. A configured callable
  `(actor, case_ref)` returns 1–16 `PriorityOption(value, label, rank)` objects with
  distinct values and integer ranks 0–100. It must expose a pure `projection_epoch()`.
  The server hashes the exact options and epoch; browser labels or ranks are never
  trusted. Fixture priorities are synthetic, not a production policy decision.

Each target must independently resolve to a current, active, scoped Mufti in the
configured directory. A candidate selector cannot create permissions, add roles,
or transfer a case to someone who could not already access it. Final checks after
all callbacks and rendering pin the actual identities, policies, action/resource
grants, deadlines and unchanged source rows. A revoked or stale write rolls back.

## Preserved history and concurrency

The original assignment table receives explicit SET_PRIMARY/CLEAR_PRIMARY events.
Original Mufti actions and historical hash payloads remain unchanged. Administrative
events add the true actor role, a required reason and a unique command identifier
to the hash. The public Mufti API rejects the new administrative actions.

Priority uses an append-only `PriorityEvent` with exact policy hash, label, rank,
reason, actor, source revisions and hash chain. SQL guards reject mutation,
deletion, broken chains, wrong pins and duplicate/no-op transitions. Both histories
use the canonical case lock and compare-and-set versions. Exact command replay
returns the original immutable event; reusing the command with new input fails.

The operational queue shows only currently readable coordination entries ordered
by their human priority. Existing Mufti assignment reads see the same assignment
events. This feature grants no new scholarly answer, approval, delivery or public
publication permission and never rewrites the original question or answer.

Downgrading the new schema refuses to erase any administrative or priority history.

## Evidence contract

- Persistence: `apps.case_assignments.test_coordination` plus existing assignment
  services and final-authorization regression tests.
- Admission/native HTTP: `apps.operational_workspace.test_coordination`.
- Fresh trust after restoration: `apps.operational_workspace.coordination_recovery_support`;
  one new populated table, one function, one trigger and nine named denied reads.
  Recovery reads do not create identities, priorities, assignments or permissions.
- Protected browser: `OperationalCoordinationBrowserTests` performs actual login,
  priority save, assignment, Mufti read, return to shared queue and revoked native
  submit, with mobile/desktop screenshots and original-source equality.

Local service success does not certify the protected browser or encrypted restore.
Those proofs must be produced for the integrated commit before point 96 is counted.
