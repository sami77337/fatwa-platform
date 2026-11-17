# Requester access-review handoff — synthetic only

Second requester slice, based on campaign integration
`21d77e6e48e2a661568c008c1864eb7e24081876`. This already includes the first
requester slice `59813f596375e614529f2c9b4316bd6ee5d30b5a` and V6 `e000cdc`.
The branch was fast-forwarded to that newer integration head before final focused
validation. Latest remote heads were inspected; the team workspace is independently owned.
This slice adds files only in `apps/requester_access_review/` and
`templates/requester_access_review/`. No earlier requester file or shared
casework, staff, guard, settings, URL, identity or CI file was changed.

## Working function

A requester with a still-valid private workspace can ask the scoped team to review
a lost copy or potentially exposed access token. The request is durable, appears
in the trusted staff queue, and can be acknowledged. The staff member opens the
existing case screen and uses its existing trusted recovery resolver to rotate or
revoke access. Only after the original grant is actually revoked can the request
be closed. A requester using a valid replacement capability sees the closed request
in their case's recent history.

Creating/acknowledging a request does not rotate or revoke a capability, mutate
case evidence, approve a ruling, send any message, or establish verified identity.
The staff state says “following up trusted verification”, never “identity verified”.
Closing means only that the original capability has been revoked; it does not
claim delivery or restoration of a replacement token.

No self-service recovery is implemented. If both the capability and live private
session are lost, this form is unavailable and the existing trusted recovery path
is still required. A public reference and the intake/idempotency cookie grant no
access to this feature. The default trusted provider/recovery resolver remain unset.

## Boundaries

- Existing `_token_case` / `_staff_case` core contexts enforce ownership, scope,
  synthetic database checks, row locks and current capability/identity checks.
  This explicit internal API dependency is pinned to the V6 service boundary.
- One review per capability digest, even on concurrent submissions. A repeated
  request preserves the original reason; a replacement capability can create its
  own request. No free-text identity/contact fields or raw tokens are stored.
- The request form is CSRF protected and bound to both the browser capability and
  case. A stale tab cannot create a review for a newly selected case.
- Staff actions re-resolve trusted identity and case scope under the core case
  lock. Expected request revision prevents stale acknowledgements/closure.
- Requesters see only reason, coarse review status and creation time. Staff IDs,
  request UUIDs, token digests, question text, answers and audit records are omitted.
- Queue: oldest 50 open requests in scope. Requester history: latest 10 reviews
  for their case. No public/private production registration or new role grants.

## Run and integration handoff

Use the owned synthetic database and Python 3.13 setup in
`apps/casework_web/REQUESTER_WORKSPACE.md`. Keep all existing synthetic-only
environment flags and connection checks. Then:

```sh
export DJANGO_SETTINGS_MODULE=apps.requester_access_review.settings
python manage.py migrate --noinput
python manage.py runserver 127.0.0.1:8000 --noreload
```

Open `/casework/`, submit a synthetic question, follow its receipt to
`/casework/status/`, and use “حفظ طلب مراجعة الوصول”. The review queue is at
`/casework/staff/` after trusted staff login. The standalone profile also lists
authorized cases so the original case editor remains reachable. The browser test
configures an explicit synthetic trusted resolver and completes the full journey.

For the campaign integration owner:

1. Integrate the first requester slice `59813f5` before this slice.
2. Add `apps.requester_access_review.apps.RequesterAccessReviewConfig` to the
   combined **synthetic-only** installed apps and apply its new migration.
3. Route requester status through `apps.requester_access_review.views.requester`;
   ordinary unlock/close/followup POSTs delegate to the earlier requester adapter.
4. Preserve the separately owned team workspace's normal GET/POST routing.
   Dispatch staff actions `access_queue`, `access_acknowledge`, and `access_close`
   to `apps.requester_access_review.views.staff`. Add a POST+CSRF button with
   `action=access_queue` in the team workspace to enter this queue. Its “open case”
   action can return to the existing team dispatcher. Do not replace a combined
   team's URL configuration blindly with this standalone profile.
5. Keep `CaseworkGuard`, CSRF middleware and trusted identity/recovery callbacks.
   All paths used are already allowed by the existing loopback guard.
6. Add the two focused test labels below to the corresponding CI steps. Shared CI
   and team files were intentionally left untouched for the integration owner.

## Focused validation

```sh
python manage.py test apps.requester_access_review.tests --noinput
python manage.py test apps.requester_access_review.browser_tests --noinput
python manage.py makemigrations --check --dry-run
python manage.py check
```

Local evidence: seven HTTP/database scenarios passed on PostgreSQL 17.12, including
concurrent duplicate requests and rotation between form verification and save.
The real Chromium 154.0.8037.57 journey passed: requester request → scoped staff
queue → acknowledgement → existing trusted fixture rotation → old access rejected
→ closure → replacement access shows history. Mobile 360px / desktop 1280px RTL
had no overflow; no external page requests. Migration application, migration drift
check, Django checks and Ruff passed.

The executor's browser sandbox helper is unavailable. The isolated synthetic
browser run used `FATWA_BROWSER_SANDBOX=0` and writable `XDG_CONFIG_HOME` /
`XDG_CACHE_HOME` under `/tmp`; the test defaults to enabling Chromium's sandbox.
Screenshots under `/tmp/fatwa-access-review-qa` contain only synthetic status,
never issuance screens or raw tokens. No PostgreSQL 18 or combined-branch CI result
is claimed here. `NOT_DEPLOYED / GATES_HOLD`.


## V6 trusted tokenless recovery — synthetic profile only (PR #225 continuation)

`apps.requester_access_review.recovery.recover_lost_access` is an opt-in
case owner recovery **without an existing tracking token**, but not without identity
proof. Its caller supplies a public FT reference and an opaque credential; the
server supplies `FATWA_CASEWORK_RECOVERY_AUTHORITY`, an instance of
`TrustedRecoveryAuthority`. This configuration defaults to `None`.

The external authority's `verify(credential, public_ref)` must independently
authenticate the requester, bind both the exact case and requester, verify the
issuer/audience, freshness, signature and revocation, and return a
`VerifiedRecovery` with an unpredictable assertion identifier. This code does
**not** issue external credentials, emulate identity assurance, or accept a
browser-selected requester or role. A public FT reference alone always fails.

On successful verification, the application performs one PostgreSQL
transaction: lock and verify the existing case; reject a reused proof ID; append
an immutable receipt containing only a digest of issuer/ID; revoke all prior
tracking tokens; issue a fresh random token; append the case's `ROTATE_ACCESS`
audit event. Original question, answer, evidence, case ID, and review history
remain unchanged. Replays, mismatched owner/case, expired attestations and
invalid claims fail closed. The replacement is displayed **once** on a private
`no-store` form and remembered in a short-lived HttpOnly browser cookie.

The synthetic Arabic page `/casework/status/` contains a recovery form only
when the trusted authority is explicitly present. Form proof is bound to the
browser's CSRF secret. A user who has neither a valid private token nor an
externally verified credential has **no recovery access**.

This is a development contract, not a configured production identity system or
approval of organizational authorization. Real identity verification, credential
delivery, MFA, customer support policy and production audit/retention rules
remain outside the current acceptance claim.

Focused tests: `apps.requester_access_review.recovery_tests`, run on both
PostgreSQL 17 and 18 by `team-workspace.yml`. No production route, real
requester data or third-party messaging is enabled.
