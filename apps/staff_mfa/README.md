# Staff MFA development mechanism — owner point 405

**Default off, synthetic development composition, NOT_DEPLOYED.** This package
implements primary verification, native enrollment, actual TOTP confirmation,
current session assurance, factor revocation and one-use recovery. Shared app,
URL, navigation and evidence-registry wiring is integrated by the coordinator.
Owner point 405 requires the protected native and aggregate restore gates on the
combined revision; a service result alone does not close it.

## Source and scope

SPEC-U14-013 / D-037 require MFA for the Mufti and organizer administrators and
explicit policy for sensitive reauthentication. Recovery cannot grant additional
permissions or bypass ownership. SPEC-U14-028 leaves first-account activation,
authentication/recovery methods and production timing policy pending. Existing
`staff_sessions` fresh-credential checks are not a second factor.

This optional implementation uses an actual local TOTP verifier and an independent
primary knowledge-factor adapter on the **currently configured actual identity
directory**. There is no provider selection, real account, email/SMS delivery,
external authenticator API or production grant. The existing pinned cryptography
library implements TOTP and Fernet; no custom cipher or OTP primitive is created.
The development adapter verifies a fabricated password; it does not declare
two factors merely because an identity or bearer credential was returned.

## Closed contract

- Enabling this mechanism requires enabled server sessions, a finite explicit
  `MfaRule`, current exact authority, an external Fernet key and primary adapter.
  Neither MUFTI nor ORGANIZER_ADMIN can receive a complete staff cookie on the
  primary factor alone. No identity, role or case grant is added by MFA.
- A fresh primary challenge binds the actual subject, role, scope digest, auth
  epoch, provider, browser/CSRF binding, surface, runtime and finite deadline.
  Enrollment and OTP forms have only pre-authentication authority.
- First enrollment requires an independent ENROLL grant and **no previous active
  or revoked factor history**. A pending secret is encrypted with exact factor
  binding, shown only in its initial native enrollment response, and activated
  only after a real matching TOTP. An abandoned enrollment does not become active.
- A factor/counter uniqueness constraint and account lock serialize successful
  use, including simultaneous submissions. Failed attempts persist and count for
  the account; restarting the challenge does not reset them. Parameters are
  supplied explicitly within engineering bounds, not selected for production.
- A completed proof is consumed once into a specific server session. Current
  factor, identity, policy and deadline checks continue through session use,
  response rendering and private streams. Revocation invalidates earlier sessions
  without deleting their history or changing their original author.
- Optional saved recovery codes are random, one-use, stored only as hashes and
  shown once after a verified enrollment. Recovery requires a freshly verified
  primary factor **and** an independent RECOVER grant. It revokes the prior factor
  and permits a verified replacement; it does not issue an access cookie by itself.
  No revoked account silently returns to first-enrollment policy.
- Revoking an existing factor requires fresh primary verification of that same
  current actor and a new TOTP with an independent REVOKE grant. A recovered
  challenge belongs to one factor generation: it cannot replace a subsequently
  enrolled factor, including after that newer factor has itself been revoked.
- Recovery and audit retain immutable attribution. A restored database cannot
  reactivate old challenges, sessions or consumed codes as current authority.
  Production in-place rollback still requires externally rotated runtime/key
  generation; application state cannot prove a rollback of all its own history.

## Integration and defaults

Install `apps.staff_mfa`, include `apps.staff_mfa.urls`, and retain the existing
`staff_sessions.middleware.SessionContext`; MFA adds no middleware. The two exact
paths are `/casework/staff/mfa/` and `/casework/operations/mfa/`, accepting only
GET, HEAD and POST under the feature gate. GET and HEAD never enroll, recover or
activate a factor. POST shares the existing login budget and CSRF protection.

The native staff and operations login handlers choose this flow only when
`FATWA_STAFF_MFA_ENABLED is True`. With that switch off, existing login behavior
is preserved only for identities without a saved factor. A saved enrollment,
including pending or revoked enrollment, vetoes legacy issuance and cookie use.
An earlier MFA-marked cookie also cannot silently become an ordinary cookie.
An enabled flow needs all of the following explicitly supplied:

- Enabled server sessions with their existing authority and runtime generation.
- The actual configured identity directory implementing `PrimaryAuthentication`,
  including fresh verification of a knowledge credential for the server challenge.
- `FATWA_STAFF_MFA_AUTHORITY` implementing `MfaAuthority`: exact actions, a finite
  aware-UTC deadline for each grant, explicit parameters, and a pure atomic,
  non-reused policy epoch. There are no fallback role grants or timing defaults.
- `FATWA_STAFF_MFA_KEY`, an externally supplied Fernet key as bytes. Only encrypted
  factor secrets and non-reversible recovery-code digests enter the database.

`apps.staff_mfa.settings` is the isolated development test profile. Its default
flag is false, with no authority or key. `test_support` supplies invented local
accounts and password hashes only within explicit test settings. It is not an
adapter for a real identity provider.

The existing access/session boundary requires an in-transaction issuance grant
that was produced by the successful second-factor verifier. Every later native
request binds the proof, subject, browser/CSRF secret, surface and server session.
The coordinator's final session-guard pass invokes `check(authorize=False)` after
all policy callbacks. This is a pure current-state pass: it retains factor
revocation, key/runtime identity, epochs and grant deadlines without invoking a
new policy or identity callback after another boundary's final checks.

Native pre-authentication pages also retain their original enrollment/start grant
deadlines and sealed factor/challenge history through rendering and that final
lease pass. They do not create a full staff binding to obtain this protection.
Completed issuance retains its new proof and session even before a subsequent
request reads the cookie. Native pages fail closed without the session-context
middleware; direct service tests do not require an HTTP request context.

The enrollment veto is independent of the MFA and session feature switches and
continues when the MFA app is removed from the installed-app list. Its narrow
model-free PostgreSQL reader checks the exact provider/subject in the existing
public enrollment tables. An incomplete or unreadable history store fails closed;
older profiles with neither the app nor its tables retain legacy behavior. This
is a veto only: history never proves a current factor or supplies an identity,
role or permission. Native tests cover passwords accepted by both real legacy
handlers and the same current directory, as well as cookies issued before first
enrollment. Fixtures use a separate synthetic MFA identity realm so the restore
proof does not enroll another helper's independently configured test account.

## Verification entry points

1. RFC 6238 Appendix B: all 18 SHA1/SHA256/SHA512 vectors, exact ASCII/length,
   explicit clock window, ciphertext tampering, wrong key and cross-factor secret.
2. Real PG17/18: enrollment/activation, no primary-only access, replay and parallel
   submissions, persistent failures, current-policy/identity/factor revocation,
   cross-account/browser/surface, atomic session-proof binding, append-only guards,
   one-use recovery and unchanged case/answer/decision originals.
3. Protected native Chromium on actual staff/operations routes: two actual roles,
   keyboard forms, widths 320/1280, traces, wrong OTP and post-render revocation.
4. Restore: historical audit remains readable with a new explicit grant; old
   authentication state never resumes by merely restoring rows or configuring a
   new permissive identity. No live enrollment, provider or production assurance.

Service and actual-handler labels are `apps.staff_mfa.test_primitives`,
`apps.staff_mfa.tests`, `apps.staff_mfa.test_campaign`,
`apps.staff_mfa.test_recovery` and `apps.staff_mfa.test_downgrade`.
Regression includes the existing staff-session
service, native and recovery tests. The tests cover real PostgreSQL transactions,
not a mocked database. Migration `0002_integrity` supplies append-only, digest,
ownership, one-active-factor, generation and one-use database guards for all nine
MFA history tables.

The protected browser label is `apps.staff_mfa.browser_tests`; its only success
receipt is `.local/qa/functional-continuation/staff-mfa-browser/result.json`.
It uses the actual campaign router, Chromium's sandbox, keyboard submission,
320/1280-width screenshots and trace archives. Two actual roles complete native
password and TOTP forms. It checks primary-only denial, hidden setup secret after
GET, invalid OTP, copied-session denial after factor revocation, native recovery
and current-policy denial followed by a positive read. OTP values come from the
seed shown in the enrollment page. Test pacing respects the production-independent
login limit; it does not weaken the product throttle.

`apps.staff_mfa.recovery_support` exports the nine tables, one trigger function,
nine triggers, `populate()` and `verify_restored()`. It requires fourteen independent
denials plus a fresh historical audit before and after those denials. The helper's
unit test rotates trust/runtime locally; a separate database dump/restore remains
the aggregate verifier's responsibility. Neither local browser-launch failure nor
unexecuted restore orchestration is reported as PASS.

## Remaining owner and environment decisions

Production primary identity verification, first-account activation, factor and
recovery enrollment policy, key custody/rotation, runtime rotation after restore,
grant durations, attempt policy and deployment transport remain unconfigured.
The native test composition uses loopback and synthetic accounts; its cookies and
key settings must not be mistaken for a production authentication deployment.
No MFA success expands a case, scholarly approval, privacy, export or publication
permission. No email, SMS, external identity-provider call or production account
is created by this package.

## Technical references and limits

- [RFC 6238](https://www.rfc-editor.org/rfc/rfc6238.html), especially sections 5.2
  and 6 and Appendix B. This defines the TOTP time-counter and reference vectors.
- [Cryptography two-factor primitives](https://cryptography.io/en/50.0.2/hazmat/primitives/twofactor/)
  and [Fernet](https://cryptography.io/en/50.0.2/fernet/). The pinned installed
  version is also inspected and tested directly.
- [NIST SP 800-63B-4 authenticators](https://pages.nist.gov/800-63-4/sp800-63b/authenticators/):
  manual OTP is not phishing-resistant. No AAL or phishing-resistance assertion is
  made by this package. Password/provider assurance, key custody, secure deployment,
  account activation and production recovery policies remain external decisions.
