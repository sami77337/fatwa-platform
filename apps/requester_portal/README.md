# V10 requester portal — closed synthetic composition

A single Arabic RTL surface for the token holder's original question, own
followups, user-facing clarifications, attachments, currently authorized answer,
audio/files, source metadata and delivery evidence. It reuses V9 canonical
services; **no models, migrations, queue, capability issuer or new role grants**.
Research notes, drafts, audit, source raw payloads, staff IDs, storage pointers,
worker leases and signing data are excluded by an explicit projection.

## Integration contract for the campaign owner

- Add `apps.requester_portal` to `INSTALLED_APPS` (local templates use app discovery).
- Route `/casework/status/` to `apps.requester_portal.views.portal` **before** the
  existing status resolver. `apps.requester_portal.urls` demonstrates this overlay;
  the standalone profile is `apps.requester_portal.settings`.
- Explicitly opt in with `FATWA_REQUESTER_PORTAL_ENABLED=True`; absence is closed.
  Keep the existing `CaseworkGuard`, CSRF middleware, no-query policy, loopback
  host/network checks, form limits and request budget. This is not a public route.
- Retain existing `/casework/status/attachments/<uuid>/` and
  `/casework/status/answer-media/<uuid>/` handlers. Every actual byte read uses
  their fresh capability/case/answer checks. No bearer URLs or query credentials.
- Existing V9 flags govern dependencies independently: attachments, multipart
  editing, explicit private media release, signed text availability, composite
  delivery and server-configured identity/capabilities/verifiers. This profile
  **does not enable them** or install signers/identity providers. The integrator
  supplies only the authorized synthetic fixture configuration.
- `services.snapshot(token=..., synthetic_fixtures_only=True)` returns:
  `public_ref`, `revision`, `evidence_version`, `clarification`, allowlisted
  `history`, `attachments`, `attachments_enabled`, `answer | None`, `answer_state`,
  `answer_label`, `delivery`, `read_confirmed=False`, and safe `access_reviews`.
  `answer` contains only `text`, `revision`, safe file `parts` and source-only
  `citations`; editorial notes/correction history stay private to staff.
- The view uses the existing browser/CSRF-bound HttpOnly capability cookie and
  native `unlock`, `leave`, `followup`, `attachment_upload`, and
  `request_access_review` actions. Successful writes redirect back to this portal.
  Stale followups retain the text for explicit retry; a switched-case proof never
  copies that text to the newly selected case. A stale upload must be reselected.
  Existing `trusted_recover` POST remains delegated to its trusted authority;
  the portal grants no self-service recovery or authority from a case reference.

`answer_state`: `UNDER_REVIEW`, `APPROVED_UNAVAILABLE`, `PRIVATE_AVAILABLE`.
`delivery.state`: `NOT_PROVEN`, `PROVIDER_ACCEPTED`, `SIGNED_DELIVERED`, `UNRESOLVED`.
These are **independent**, not a shared linear workflow. Mixed failed/unknown parts
remain unresolved, with accepted/verified/failed/unresolved counts shown separately.
Acceptance can itself need human followup; it never certifies delivery. Partial
signed receipts cannot certify the whole answer. Page/file access creates no
reading or listening claim and no delivery attempt.

The aggregate holds V9's token-authorized case/queue transaction across its
component reads and checks the final revision/capability. New facts/answers,
revoked capability, revoked approving identity or unavailable source/media cannot
fall back to an old answer. Existing signed-text policy (#225) is preserved: its
text requires both its explicit visibility flag and complete verified delivery;
multipart content requires the separate current private release.

## Focused verification / remaining boundaries

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/pg17/bin --major 17 \
  --settings apps.requester_portal.settings -- \
  python manage.py test apps.requester_portal.tests --noinput
# Run apps.requester_portal.browser_tests similarly with installed Playwright/Chrome.
```

The integration owner should include those two labels in V10 CI. Browser artifacts:
`.local/qa/v10-requester/browser/`. Evidence and historical failures are in
[V10_REPORT.md](V10_REPORT.md). No shared file needs a lane-owned edit; registration
belongs to the coordinator.

V9 deliberately withholds composite receipts until current private availability;
this portal keeps that boundary. Missing/stale evidence displays unresolved, not
cached success. Legacy text projection has no acceptance count, so it remains
conservative rather than inferring provider acceptance. Full source text/rights,
real accounts, production recovery, real sends, new permissions and public
publication remain outside this app. The profile's UI switch does not revoke
existing independently guarded media capabilities.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**
