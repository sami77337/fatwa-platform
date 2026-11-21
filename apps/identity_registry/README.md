# Human identity registry — disabled synthetic development unit

This app separates an immutable platform identity from an optional internal Person.
It implements original rows **153, 156, 158, 421, 439** as one connected human workflow
(U14-002/004/006/019; D-036/037/055). Row 154 is an illustrative platform list and
receives no credit. Row 156 is supported by actual native UNLINKED → POSSIBLE_MATCH
→ independently VERIFIED_LINK → explicitly revoked UNLINKED transitions, not an enum
alone. Final completion remains dependent on the exact integrated protected-browser
and encrypted-recovery evidence. Production gates, D-067 role decisions and actual
external identity verification remain held.

## Actual workflow

1. An authorized operator captures the **existing bound origin** of the selected
   canonical case. A source-backed origin must resolve its existing immutable
   SourceReceipt and original EvidenceBinding; its source, account, sender, original
   digest and historical display name are checked exactly. The UI accepts no typed
   platform ID, inferred name match, photo match or AI identity suggestion.
2. A native website case is explicitly recorded as `WEBSITE_SESSION`. Its original
   server-created requester key is a session identity, not proof of a civil identity
   or a login account. Distinct source/account/sender triples remain distinct even
   when historical display names match. Repeated observed exact origins can share a
   PlatformIdentity without creating any Person.
3. A human can create an optional Person with an internal label and documented
   purpose, then propose a link with explicit evidence. A **different provider/subject
   human** with current VERIFY authority reviews that proposal. The author cannot
   approve their own proposal, and LINK permission does not imply VERIFY permission.
   Rejection leaves the identity unlinked. Existing verified links cannot be silently
   replaced by another proposal.
4. Explicit UNLINK revokes the current verification and appends a new membership;
   all prior decisions remain available within current audit scope. The old reviewer
   record is historical evidence, never a stored access grant or civil-name claim.
5. MERGE moves all current identity links from one Person to another. SPLIT moves an
   explicit nonempty proper subset. They have separate current capabilities, an exact
   before/after preview, affected case references/versions, a human confirmation and
   reason, optimistic history pins, and an append-only operation plus membership rows.
   A changed preview cannot apply. The former Person and historical memberships remain.

Neither link nor merge/split modifies a canonical case, original question, followup,
answer, author, requester key, source receipt, tracking token, access grant, return
route, delivery target or public scholar profile. Old case facts are never inferred
as facts of a new case. The preview states that already exposed information cannot
be retracted by a local identity correction. There is no public identity endpoint.

## Authority and composition

`FATWA_IDENTITY_REGISTRY_ENABLED=False` and
`FATWA_IDENTITY_REGISTRY_AUTHORITY=None` are the closed defaults. Development execution
also requires the existing owned PostgreSQL synthetic queue and recovery-admission
guards. `IdentityAuthority.permits()` receives the current provider, subject,
authentication epoch, exact case reference, operation and resource pins. Capabilities
are READ, SEARCH, CAPTURE, CREATE_PERSON, LINK, VERIFY, UNLINK, MERGE, SPLIT and AUDIT;
no role matrix, wildcard or historical permission binding is inferred.

Every boundary requires a pure atomic authority revision and trusted-directory
revision covering active role, case scope, authentication epoch and expiration.
Configuration replacement is compared by **object identity**, not value equality.
The shared graph mutex precedes UUID-ordered locks on every current actor-scoped case.
A command affecting an identity or Person with an unscoped case is denied as a whole.
Scoped listings omit incomplete groups without exposing hidden names, counts or IDs.
Source/history fingerprints include empty sets and original binary digests. Permission
callbacks and identity re-resolution finish before the final pure snapshots/deadlines.
Each native write and its rendered response share one transaction, so late rendering
revocation rolls back the submitted command.

The browser state is CSRF/actor/case-bound and signed for ten minutes; it contains
version pins, never a grant. The merge/split preview is independently signed and
recomputed exactly at confirmation. No mutation service accepts a browser role or a
human-supplied source-account identity.

## Integration

Register `apps.identity_registry`. Native dispatcher calls
`apps.identity_registry.editor.workspace` for `editor.ACTIONS`:
`ir_open`, `ir_capture`, `ir_person`, `ir_propose`, `ir_decide`, `ir_prepare`, `ir_apply`,
`ir_history`. All use `/casework/staff/` with existing native authentication and CSRF.
The current-case Mufti tab is `ir_open`. There are no new anonymous routes, storage
objects, network calls or credentials.

Six tables are append-only and sealed: PlatformIdentity, IdentityObservation, Person,
LinkProposal, RegistryOperation, IdentityMembership. PostgreSQL validates exact bound
origins, independent review, current previous membership, merge/split selection and
complete operation membership at commit. It rejects UPDATE/DELETE and incomplete
operations. The human authority itself remains an external current prerequisite; SQL
does not fabricate a permission grant.

`recovery_support.TABLES`, `FUNCTIONS`, and `TRIGGERS` enumerate the six tables, two
functions and seven triggers. `populate()` creates two source cases and complete
verify/merge/split/unlink history. `verify_restored(pins)` uses a fresh explicitly
supplied synthetic directory/authority, checks exact history and original source
bytes, executes missing-authority, missing-directory and revoked-reader denial
branches, then proves a positive current read after restoration. Its denial counters
come from those executed branches. No persisted authority is reconstituted from rows.

## Verification labels

- `apps.identity_registry.tests.IdentityRegistryTests`: source preservation,
  separation, real verification states, scoped corrections, concurrency, SQL guards,
  current identity/policy changes and rollback.
- `apps.identity_registry.test_http.IdentityRegistryHTTPTests`: actual campaign
  dispatcher, signed native forms, independent actors, CSRF, preview/apply and late
  command/render denial.
- `apps.identity_registry.test_recovery.IdentityRegistryRecoveryTests`: nonempty six
  table history, fresh explicit trust and executed denial counters.
- `apps.identity_registry.browser_tests.IdentityRegistryBrowserTests`: protected
  Chromium native two-human capture/proposal/verify/merge/split/unlink, current reader
  revocation, unchanged original records, 320/1280 Arabic RTL screenshots and traces.
  Proof: `.local/qa/functional-continuation/identities-browser/result.json`.

Owned service/native/recovery set: 21 tests PASS on real PostgreSQL 17.11 (12.124 s)
and PostgreSQL 18.7 (10.989 s). The protected-browser class is ready for hosted CI
using FATWA_FASTBUILD_BROWSER with chromium_sandbox=True. Exact integrated browser
and encrypted-recovery evidence remain the coordinated run’s responsibility; this
app does not assert a local browser pass or bypass the browser sandbox.

### Configured-directory follow-up

The registry now requires the **exact configured** identity provider, or the native
RequestDirectory wrapping that same provider object. An active same-named alternate
directory cannot replace a revoked configured actor, even when the policy provider
ID and authentication epoch strings match. Native rendering also continues to reject
a value-equal, same-epoch configuration replacement and rolls back the entire write.
Original source records, cases and tracking tokens remain unchanged by denied writes.

The complete owned service/native/recovery set after this follow-up is **24/24 PASS**
on PostgreSQL 17.11 (24.434 seconds) and PostgreSQL 18.7 (24.601 seconds), recorded in
`identity-directory-pg17.log` and `identity-directory-pg18.log`. The existing three
recovery denial counters and hosted browser evidence requirement are unchanged.

### Classification of actual identity origins

Current case `READ` classification and the exact original `SOURCE_RECEIPT` are
additional conditions for capture, detail, audit and intentional registry writes.
Search requires independent `SEARCH` permission on both sources before names,
people or group counts are assembled. A hidden case is omitted from discovery;
an explicitly selected hidden origin is denied. The existing identity authority,
source-bound provenance, independent human verification and optimistic guards
continue to apply. There is no invented global `IDENTITY` classification target.

The outer privacy context outlives registry permission callbacks. A late privacy
withdrawal discards the projection and rolls back the intentional command.
`apps.identity_registry.privacy_tests` proves origin-level capture denial,
independent search authorization and rollback after the last domain callback.
