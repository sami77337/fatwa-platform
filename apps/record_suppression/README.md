# Reversible record suppression — owner point 387

Development composition only. Default off. NOT_DEPLOYED; existing production gates remain HOLD.

## Saved requirement and scope

The source is `docs/product/v12_scope_evidence/specifications.json`,
`SPEC-U14-020`: soft deletion excludes a record from ordinary use while retaining
what the restoration policy permits; closure, archive, publication withdrawal,
anonymization and purge are separate operations. `SPEC-U14-019` requires a
private immutable audit. `SPEC-U05-026`, `SPEC-U14-023` and `SPEC-U15-024` prohibit
stale search, managed copies and recovery from reviving withdrawn access.
Decision `D-043` separates the lifecycle states and leaves retention periods for
a later decision. `D-055` preserves originals/references and rejects blind cascade
purge. These are recovered repository source records, not a new owner policy.

This app implements point **387** over the existing closed material catalog in
`apps.data_privacy.catalog`. It reuses current source pins and reader boundaries.
It does not add states to `Case.stage` or change the existing `case_lifecycle`
OPEN/CLOSED/ARCHIVED transitions. It never edits a question, answer, attachment,
transcript, publication, media blob or source permission.

| Current suppression state | Command | New state |
| --- | --- | --- |
| No decision / ACTIVE | SOFT_DELETE | SOFT_DELETED |
| SOFT_DELETED | RESTORE | RESTORED |
| RESTORED | SOFT_DELETE | SOFT_DELETED |

Every transition creates a new immutable event. RESTORE enables ordinary current
checks again; it does not reinstate a revoked identity, source right, publication
lease, approval, token or privacy grant. No automatic expiry or retention period
is selected. A suspended source remains suspended until a separately authorized
restoration. The source's current permissions continue to apply.

## Explicit administrative contract

Settings are `FATWA_RECORD_SUPPRESSION_ENABLED=False`,
`FATWA_RECORD_SUPPRESSION_AUTHORITY=None` and
`FATWA_RECORD_SUPPRESSION_JOURNAL=None`. Root integration owns shared registration.
There is no production adapter or default grant.

`SuppressionAuthority` receives the actual MUFTI or ORGANIZER_ADMIN identity,
provider, authentication epoch and an exact target pin. ORGANIZER cannot administer
this ledger. ENTER, READ_AUDIT, SOFT_DELETE, RESTORE and RECONCILE are distinct
mandates. A finite `(kind, UUID)` candidate list is not a grant. A case-bound target
must remain in the administrator's current case scope. No role impersonation,
scientific answer permission or permission-template edit is introduced.

The native paths are `/casework/staff/record-lifecycle/` and
`/casework/operations/record-lifecycle/`, GET/POST only. The original CSRF-bound
staff/operational sessions remain authoritative. A server-rendered preview pins
the source digest, decision head, full ledger watermark, actual actor, current
policy and deadline. Confirmation is bound to this browser session. The exact
preview is recomputed under fresh authority before appending. An old/repeated
confirmation conflicts and cannot create another audit event.

Administration displays identifiers, state, reason and audit metadata only.
It does not use a bypass to reveal suppressed question/answer text. History remains
accessible only with READ_AUDIT, so an explicitly authorized administrator can
restore a record whose ordinary read is unavailable. Pending reconciliation counts
require all the affected exact audit/reconciliation mandates before display.

Policy and identity callbacks run before final pure checks. The guard is also
retained through the final staff-session callback via
`staff_sessions.integration.retain_final_guard`; domain permissions cannot be
revoked after the last source check and still release an old response.

## SQL history and the independent current floor

`SuppressionEvent` is append-only and hash chained globally and by target. The
PostgreSQL trigger rejects updates, deletes, invalid transitions, out-of-sequence
inserts, role/identity omissions, invalid reason hashes and inconsistent canonical
seals. Populated migration reversal fails explicitly. Native commands and restored
applications retain original actor metadata; a reconciliation separately records
the current applying administrator, time and reason.

A database backup alone cannot prove that no later deletion occurred. Therefore
ordinary use additionally requires the **current independent metadata journal**.
`LocalJournal` is a development adapter for an explicitly initialized private
local directory outside database/private-media backup roots. It uses a locked
compare-and-swap append and atomic write with file and directory fsync. Symlinks,
hard links, foreign ownership, permissive directory/file modes, missing files,
wrong ledger identity, malformed records and broken chains fail closed.

The journal contains target UUIDs, original hashes, decision/chain IDs, the real
administrative actor/epoch, state and time. It stores the **hash** of the reason;
it contains no question, answer, transcript, original filename, credential or
requester capability. The private SQL audit retains the human reason.

The metadata append precedes the SQL append. If the SQL transaction or final
policy check then fails, the newer journal remains. This deliberately closes
ordinary use until reconciliation; it cannot silently expose the old SQL state.
If a backup is older than the current journal, the same prefix mismatch closes
use. The native RECONCILE preview requires a separate mandate for every missing
exact source/decision and replays the immutable decisions with an applying audit.
Reconciliation is limited to 128 decisions per explicit confirmation so the
native request remains bounded. Ordinary use stays closed between batches until
the complete SQL prefix matches the current floor.
An inconsistent/non-prefix or older journal is rejected, not silently adopted.

The source checkpoint must survive separately and be supplied during recovery.
The app never regenerates a missing current floor from restored SQL. A deployment
that loses or rolls back **both** the database and its independent trusted floor
has lost the evidence needed to detect that rollback; this development adapter
does not claim to solve that operator trust/storage failure. No production backup
expiry, retention schedule, remote durability or availability policy is selected.
The bounded journal currently permits 4,096 decisions; reaching the bound denies
new transitions instead of discarding older decisions.

## Current reader coverage

The independent veto runs before `data_privacy.services.applicable` can return
for a disabled classification feature. It therefore applies with privacy both on
and off and supplies no privacy permission. Recorded decisions cannot disappear
by disabling/omitting this app. It verifies the resource and its canonical case;
SOFT_DELETED on either rejects ordinary use. Every admitted source contributes
pure pins to all outer privacy projections, through response and final session
checks. No fresh permission callback runs in those final pins.

| Existing consumer | Current enforcement |
| --- | --- |
| Staff/requester case, follow-up and answer work | CASE and original source boundaries; exact ANSWER veto before use |
| Idempotent intake replay | `_public` independently checks the saved case before returning a reference |
| Organizer queue/details/notes/editors | Existing actual-actor operational privacy gates before rows/counts |
| Case lifecycle desk/inbox | CASE veto plus retained pure checks after its final callbacks; no state conversion |
| Attachments, answer parts, transcript links, source receipts | Existing original/source privacy calls before DTOs, labels and bytes |
| Precise/timed/PDF citations and scholarly links | Existing pinned source boundaries, including nested source consumption |
| Canonical FTS and research/library search | Current source veto before hits, snippets, facets and counts; stored index is not authority |
| Selected exports / offline readers | Current source checks before returning an already built managed artifact |
| Library / publication / media / knowledge / collection / teaching derivatives | Exact copy and current consumed-source gates; public status does not override suppression |
| Scheduled/destination publication | Existing source permission boundaries continue to apply |

A copied source blocks its managed derivatives where those derivatives consume
that saved source pin. A separately created independent original is not silently
identified by fuzzy text matching. The generic private storage backend remains a
byte store, not a grant; owner readers enforce the catalog gates. Security-session
ledgers, account identities and arbitrary uncataloged Django models are outside
this material-only command interface.

## Verification and recovery contract

Focused tests use fresh owned PostgreSQL 17/18 clusters and actual service/HTTP
readers. They cover exact transitions and roles, source preservation, CAS and
replay, SQL integrity, late callbacks and response rendering, an older SQL state
with a newer independent journal, native reconciliation, existing FTS/ZIP/file
readers, public navigation and Range bytes, and separation from CLOSED/ARCHIVED.
The test profile supplies finite synthetic grants only.

`recovery_support` declares one nonempty table, one SQL function and one trigger.
Its independent journal is retained outside the database/private-file capture;
`fresh_trust` requires that current external checkpoint and never bootstraps it
from restored rows. `verify_restored` checks named current-use denials followed by
an actual positive source read, immutable audit protection and unchanged originals.
The separate core recovery scenario verifies reapplication after rollback to an
older SQL prefix. No purge or anonymization is asserted.

Protected browser entry:
`apps.record_suppression.browser_tests.RecordSuppressionBrowserTests`, one journey.
It uses actual admin, organizer and requester forms, requires the protected
Chromium sandbox, and records screenshots at 320/1280 plus trace/result artifacts
under `.local/qa/functional-continuation/record-suppression-browser/`. Local service
or HTTP success is not hosted-browser evidence.

### Deliberately unresolved: points 389 and 390

Anonymization (389) requires a decided identity-data scope, authorized process,
impact on the ordinary Mufti identity display, reversibility and preserved audit.
Purge (390) requires a decided retention/deletion workflow, impact review across
shared physical files and human-reviewed texts, explicit authorization, managed
index/AI/cache/backup handling and a tested durable anti-resurrection record.
`SPEC-U14-021/022/023` and D-043/D-055 do not authorize choosing those policies here.
Neither operation is implemented or counted by this app. No physical deletion or
irreversible anonymization endpoint is present.

### Aggregate recovery composition

Run this component's `populate()` **last**, after earlier component populations.
Once a suppression history exists, missing/disabled current-floor configuration
must close ordinary source use globally: an older SQL backup cannot know which
additional sources a newer external floor suppresses. After population, wrap
all source-reading stages and all component restored verifiers in
`recovery_support.current_floor(pins["record_suppression"])`. That context sets
only the suppression feature and its independently supplied metadata journal.
It grants no identity, administrative action, domain use or privacy permission and
does not replace other components' explicit current trust.

The helper also exercises an **older SQL prefix with a newer current journal**:
a real authorized decision survives outside a rolled-back SQL transaction;
ordinary reading is rejected, an explicit RECONCILE replays the missing decision,
the reapplied deletion still rejects use, and a separately authorized RESTORE
permits a positive current read. These negative checks use an isolated copy of
the independently read external floor, then roll back fixture SQL; the original
checkpoint, captured audit and source histories are verified unchanged.

### Local results for checkpoint `14bbcf1`

On 2026-11-21 the five focused service/native-HTTP/reader/recovery/session test
modules passed **30/30 on PostgreSQL 17.11 (41.277 s)** and **30/30 on PostgreSQL
18.7 (41.618 s)**. Logs: `suppression-checkpoint-pg17.log` and
`suppression-checkpoint-pg18.log` in the work workspace. These are local owned
clusters, not hosted browser or aggregate restored-browser evidence.

The previous broader 92-case run passed all 64 existing lifecycle/privacy
regressions and 27 new cases; its one failure was the new session fixture's
missing exact metadata read grant. That fixture was corrected before the 30/30
checkpoint run. The earlier failing run is not reported as an aggregate pass.
The current-floor aggregate adapter and its additional interoperability/replay
checks are a subsequent checkpoint with their own reported results.

### Current-floor follow-up results

The follow-up `apps.record_suppression.test_recovery` passed **2/2 on PostgreSQL
17.11 (1.952 s)** and **2/2 on PostgreSQL 18.7 (2.198 s)**. The restored verifier
now performs ten named current-use denials, including a newer external decision
surviving SQL rollback, and requires an actual positive read after all denials.
The other test composes an unrelated existing case reader with the current floor
while the suppression management authority remains absent and the identity and
privacy settings remain unchanged. Logs: `suppression-current-floor-pg17.log`
and `suppression-current-floor-pg18.log`.

The older `config.settings.casework_test` profile, which does not install this
application or create its table, also passed `tests.casework.test_core` and
`tests.casework.test_http`: **33/33 on PostgreSQL 17.11 (6.399 s)** and **33/33 on
PostgreSQL 18.7 (6.047 s)**. This checks the no-history compatibility path through
real core and HTTP consumers. Logs: `suppression-legacy-profile-pg17.log` and
`suppression-legacy-profile-pg18.log`. Hosted browser and full aggregate recovery
remain separate integration gates; these local results do not assert either one.
