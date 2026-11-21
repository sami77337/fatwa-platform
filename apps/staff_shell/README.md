# Installable staff interface and readable dark surfaces

Original owner point **55** is implemented as a separate default-off staff PWA
shell. `FATWA_STAFF_PWA_ENABLED=True` adds a same-origin manifest and worker under
`/casework/staff/`; the worker has no control over requester tracking routes.
The manifest uses the actual staff start URL, standalone display and validated
192/512 PNG icons. Installation never supplies an identity or resource grant.

Every real case request still reaches the current server session, identity,
case scope and existing CSRF/operation boundary. The worker does not open Cache
Storage, retain a response, queue a POST, synchronize credentials or store an
answer. Offline navigation returns a static 503 screen without a case reference,
question, answer or mutation form. Reconnection checks current access afresh.
There is no claim of offline private work. Only marked staff HTML gets explicit
same-origin script/worker/manifest CSP directives; the default and requester
policies stay closed. No unsafe-inline, unsafe-eval or browser sandbox change.

Original point **255** is implemented with real `prefers-color-scheme` styles on
public reading pages, staff native surfaces and the separate offline library
reader. Text and resource permissions do not change when the browser preference
changes. The existing functional design remains provisional; this is not final
branding, specialist design approval or a whole U09-004 closure.

## Verification contract

`apps.staff_shell.tests` runs true guarded campaign HTTP tests for default-off
behavior, bounded assets, manifest scope, real image bytes, CSP, requester
isolation and unchanged private/no-store headers. Protected browser evidence is
required from both exact test identities in `apps.staff_shell.browser_tests`:

- `StaffPWABrowserTests.test_installable_staff_scope_requires_live_authorization_and_never_caches_cases`
  uses a fresh temporary persistent sandboxed Chrome profile, real manifest and
  installability checks, a real offline transition, empty Cache Storage, no
  private offline screen/actions and revoked-access rejection after reconnection.
- `DarkModeBrowserTests.test_system_theme_switch_preserves_published_content_with_readable_dark_surfaces`
  changes the actual browser media preference, checks unchanged authorized
  published text, measured rendered contrast and light/dark mobile/desktop pages.

There are no owned durable tables or file originals to seed in the encrypted
restore inventory. Existing case authentication and restored current-authority
gates remain mandatory. Local HTTP success alone does not count browser proof.

Synthetic development only. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
NOT_DEPLOYED. No installed application is claimed on the user's own device.
