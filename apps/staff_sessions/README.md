# Server staff sessions and exact operation reauthentication

**Development composition only; default off; NOT_DEPLOYED.** No live identity
provider, credential, MFA factor, production expiry policy or administration grant
is supplied. Owner **406** / SPEC-U14-014 has a functional revocation unit for the
actual `/casework/` MUFTI and `/casework/operations/` identities. Owner **407** /
SPEC-U14-013 has one concrete policy-controlled sensitive operation:
`REVOKE_SESSION`. Owner **405** remains unproved: a synthetic credential verifier
is not MFA. D-037/U14-028 identity, recovery and production permission decisions
remain external inputs.

## Composition

Register `apps.staff_sessions`; migrate its two migrations in the owned development
PG17/18 composition. Keep these settings closed:

```python
FATWA_STAFF_SESSIONS_ENABLED = False
FATWA_STAFF_SESSION_AUTHORITY = None
FATWA_STAFF_SESSION_RUNTIME_EPOCH = None
```

Keep `apps.platform_recovery.middleware.MaintenanceGuard` first. Add
`apps.staff_sessions.middleware.SessionContext` second, before the material/private
media, CSRF and preview guards. Include `apps.staff_sessions.urls` at both
`casework/sessions/` and `casework/operations/sessions/`. Permit only GET, HEAD and
POST in the shared closed guard. Add a conditional “جلسات الحساب” link to the
corresponding staff and operational navigation. No shared configuration, guard or
route edit is included in this app commit.

The existing staff and operational access modules register opaque session IDs in
their existing signed, CSRF-bound cookies. They preserve each actual subject, role,
case scope, auth epoch, identity provider, browser binding and original shorter
expiry. The operations cookie keeps its original path; the separate operations
session-management URL is necessary for a native browser to send it. A legacy
cookie lacking a server ID is denied when this feature is enabled; a managed
cookie is denied when it is disabled. There is no permissive fallback.

## Authority and records

`SessionAuthority` supplies current explicit `ISSUE`, `USE`, `LIST`, `READ`,
`REVOKE`, `LOGOUT` and `AUDIT` decisions for the actor and exact resource. Neither
MUFTI nor ORGANIZER_ADMIN implies administration. Listing is limited to the actor's
64 newest records; an administrator must name an exact target and possess current
READ and REVOKE grants. All source permissions remain with their existing owners.

Four append-only tables record creation, revocation, fresh proof and proof
consumption. SQL validates canonical payload hashes, immutable updates/deletes,
real foreign-key relationships, finite operation names and linked proof targets.
Credentials, cookies, CSRF secrets, questions, answers, IP addresses and user agents
are not stored in these records. Metadata and hashes are never a permission grant.
A trusted DB owner capable of disabling triggers or replacing the database is
outside this application-level immutability guarantee.

`SessionContext` holds a request-local reference that expires at the end of the
request or stream. `RequestDirectory` rechecks current registry/policy/identity and
deadline on resolution and on its pure projection revision. Resolution inside an
existing owned queue transaction locks the exact session row; revocation uses the
same lock. These operations therefore serialize without introducing a request-wide
transaction around AI/provider calls. Ordinary response rendering is checked again
before return; synchronous private stream chunks are rechecked before release.
Requests admitted before a later revocation can have already committed work; that
history remains attributable to its original author.

Successful CSRF-protected logout records server revocation before returning the
redirect. Copying the previous cookie and CSRF secret cannot restore it. An already
unauthorized cookie is denied rather than reporting a successful server logout
that did not occur. A valid authorized session can still explicitly revoke an
expired or unavailable target session. No target session permission is revived.

## Fresh verification

`SessionAuthority.reauthentication` returns an explicit required/not-required rule
and a finite freshness duration (1–300 seconds is an engineering bound, not a
production policy default). The current configured directory must implement
`FreshAuthentication.authenticate_fresh(credential, challenge=...)` and declare
its actual versioned method ID. Its adapter must actively verify the supplied
credential for this challenge. Existing directory resolution or copied auth
metadata cannot be substituted. The synthetic test adapter calls its normal
`authenticate` method and declares `SYNTHETIC-current-credential.v1`.

One process-wide daemon worker bounds fresh-verifier waiting to 20 seconds and
concurrency to one. An adapter that ignores the deadline retains the slot until it
exits; busy retries fail immediately. The controller never writes a late result or
hands it to another request. This does not kill Python code or establish a network
transport policy for a future external adapter. The call is rejected inside an
outer database transaction. Provider credentials are never logged or persisted.

After the provider returns, the service rechecks actor, session, scope, policy,
expiry and target before saving. The immutable proof binds the current session,
`REVOKE_SESSION`, exact target ID and digest, policy/directory versions, challenge
digest, actual method and finite freshness. The browser then requires a separate
human confirmation. Revocation and one-use consumption commit together under
locks. Cross-session/actor/target reuse, changed methods/policy, stale proofs,
malformed or unavailable provider responses and late results fail closed. No
answer, scholarly decision, publication, delivery or administrative role action
can be dispatched by this unit.

## Restore behavior

A session also pins the explicitly configured runtime generation and actual owned
PostgreSQL database name/OID. A fresh restore database and a rotated runtime epoch
invalidate historical sessions while preserving the audit. Production restoration
in place/PITR requires an externally managed generation rotation; an app cannot
infer a rollback of all persisted state in the same database. Do not treat a
recovered old generation as fresh authority.

`apps.staff_sessions.recovery_support` exports `populate`, `verify_restored`,
`TABLES` (4), `FUNCTIONS` (1), `TRIGGERS` (4) and eight explicit `DENIALS`:
`sessions_disabled`, `missing_authority`, `missing_directory`,
`missing_runtime_epoch`, `revoked_audit_grant`, `cross_actor_audit`,
`inactive_actor`, `restored_session_runtime`. Restored rows are read only with a
newly configured trusted identity and an explicit AUDIT grant. That positive audit
read does not restore an authenticated browser session. The consumed proof remains
consumed, the revoked target stays revoked, and the original question, human answer
and decision stay unchanged.

## Evidence entry points

- `apps.staff_sessions.tests.StaffSessionTests`
- `apps.staff_sessions.test_recovery.StaffSessionRecoveryTests`
- `apps.staff_sessions.browser_tests.StaffSessionsBrowserTests.test_native_mufti_and_admin_fresh_confirmation_revoke_only_exact_session`

The browser test requires actual campaign routes/middleware, protected Chromium
(`FATWA_BROWSER_SANDBOX=1`, `chromium_sandbox=True`), live native forms and two actual
roles. It imports fixture modules without importing TestCase classes for discovery.
It writes `.local/qa/functional-continuation/staff-sessions-browser/result.json`,
320/1280 screenshots and traces. It does not patch pages, guard routes or identity
roles. Result receipts explicitly report `mfa_assurance: NOT_EVALUATED`.

Remaining scope: real MFA method/provider selection and enrollment/recovery;
production identity policy and limits; deciding which other sensitive operations
require fresh verification and wiring those exact operations; legacy standalone
training-profile sessions outside these two native casework surfaces. No existing
training credential is silently promoted into this registry or into a real MFA
claim. Final design remains excluded.
