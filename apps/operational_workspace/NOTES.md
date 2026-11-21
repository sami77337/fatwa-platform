# Organizer internal notes

This recovers the unfinished operational-note boundary and implements original
owner row **100**: «يمكنه إضافة Internal Notes لا تظهر للسائل.» Its direct
specification is **SPEC-U02-032**. Other organizer actions in rows94–99 and the
production U03 policy are separate work; a notes page does not close them.

## Behavior

An actual currently authenticated ORGANIZER, ORGANIZER_ADMIN or MUFTI with the
explicit grants can open internal notes from a scoped operational queue card or
detail. A native form appends a note, with the actor/provider/epoch and time, to the
existing immutable `OrganizationRevision` history. Corrections are new notes;
previous notes are retained. The note is limited to2,000 characters. The established
metadata history limit of256 revisions remains in force.

Tags and question types are copied from the current canonical metadata row inside
the lock. They are never taken from this form. The original question, evidence,
answer revision, approval, case stage, publication and delivery records remain
unchanged. No new table, migration, public write route or external message is added.
Requester status does not expose the notes, including the newly appended one.

The independent feature switch `FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED` defaults
false; `FATWA_CASE_ORGANIZATION_ENABLED` and the operational workspace must also be
enabled. The root configuration owns the explicit false setting. The module uses
`getattr(..., False)` so missing configuration remains closed.

## Authorization and consistency

Every visit and every retry needs current READ_CASE. READ_INTERNAL_NOTES and
ADD_INTERNAL_NOTE are independent exact per-case/per-actor/role grants on section
`internal_notes`. An add-only user can write but sees no previous or newly saved
note body. A read-only user sees history without a write form. A queue read or a
role label grants neither permission. No organizer identity is converted to MUFTI;
the existing scholarly services retain their MUFTI-only checks.

Native rendering stays inside the canonical case lock and the operational
transaction. It rechecks positive and negative grants, configured directory and
policy object identities/epochs, identity expiry, session expiry and both note
feature flags after callbacks. Revocation during final rendering discards the
entire page and rolls back a newly appended note.

The source fingerprint advances by exactly the one inserted note row. It never
adopts a fresh entire database snapshot after a write; an unrelated callback append
is detected and rolled back. The shared private persistence primitive grants no
access by itself. The existing public Mufti metadata service retains its own
identity boundary and final authorization checks.

Optimistic pins cover metadata version, canonical case revision and evidence
version. A stale new command fails. Retrying the identical command is idempotent
even after a later independently authorized metadata change, because the command
digest binds the action, exact submitted note and original version pins rather
than a new metadata snapshot. Reusing that command for different text fails.
Current authorization is still required for an idempotent retry.

The native form uses seven application fields plus CSRF under the existing
product field/body budget. Unknown and duplicate fields, attempted role/tag/type
inputs, missing CSRF, arbitrary cases and inactive actors fail closed. Text is
rendered with template escaping. Private response headers and the existing
CSRF-bound operational session remain in use.

## Verification contract

Affected labels:

- `apps.operational_workspace.test_notes`
- `apps.operational_workspace.test_notes_recovery`
- Existing operational service, native HTTP, retry and recovery labels.
- `apps.case_organization.tests` for shared persistence regression.

Protected browser identity:
`apps.operational_workspace.browser_notes.OperationalNotesBrowserTests.test_native_organizer_notes_preserve_source_and_remain_hidden_from_requester`.
It performs real organizer login, native note creation and history rendering, then
opens requester status in a separate browser context with the actual fixture token.
The requester sees the case reference with neither old nor new internal notes.
It checks independent read/add revocation, preserved originals and RTL widths320
and1280. It emits actual page errors and external requests, screenshots, staff and
requester traces and
`.local/qa/functional-continuation/operational-notes-browser/result.json` only after
a successful protected run. Local service tests are not substituted for that run.

Recovery helper: `apps.operational_workspace.notes_recovery_support`. It adds no
table inventory; its notes live in the already covered OrganizationRevision table.
It populates actual approved case and metadata records through existing services,
adds an organizer note and records exact row fingerprints. After closing the
connection it reads the immutable notes using newly supplied current identity and
explicit note grants. It records seven actual denials: disabled note feature,
disabled metadata feature, missing directory, missing authority, revoked identity,
revoked case read and revoked note actions. It then performs a successful read
again and proves all source/metadata rows unchanged. No requester credential or
operational grant is serialized in recovery pins.

The helper is not itself encrypted-restore evidence. Root integration must execute
it after the real encrypted drill and include the exact browser identity before
crediting row100. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
