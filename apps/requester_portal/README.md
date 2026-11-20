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

## V11 completion: reply and file in one step

The native followup form now submits `action=reply` as multipart, with the existing
case/CSRF-bound `form_proof`, revision and literal text, plus optional
`reply_attachment` and `synthetic_only=yes` when a file is selected. A native empty
file control is explicitly accepted as text-only; arbitrary extra fields, duplicate
fields, dual text/file representations and non-hex proofs are rejected. The
legacy text-only `followup` action and standalone upload remain compatible.

`submit_reply(token, text, expected_revision, attachment=None,
synthetic_fixtures_only=False)` composes the existing `casework.add_followup` and
`case_attachments.upload` services. `attachment` is exactly
`{raw: bytes, filename: str, media_type: str}`. A reply to an active clarification
and its optional file commit atomically. Failure leaves the clarification, previous
approval and evidence untouched; success invalidates old answer availability.
Storage digest locks enclose the outer authorized queue/case transaction, preserving
the V9 filesystem/GC contract. Existing rollback orphan policy is unchanged; this
service never guesses which external blob to delete.

No Mufti adapter or new table is needed: the same Case gets one new evidence/event
for text, and another for the optional file. The returned canonical requester status
contains the final revision (advance +1 without a file, +2 with a file). The existing
Mufti `read_workspace_case` and attachment services see both immediately. The
original source/question remains unchanged; no origin event or external send is
fabricated.

The portal adds an actionable next step and a combined chronological conversation
including attachment links. After a successful redirect, a signed 90-second,
HttpOnly, CSRF/capability/case-bound notice confirms the saved action once. It
contains only case reference, revision, action kind and browser binding; no text,
file, raw token or answer. It is not access authority, durable audit or reading
proof. A stale case-switch form cannot transfer text, a file or a notice.

A transient integrity/storage/database read failure now shows an empty retry screen
with HTTP503 and no-store, retaining a still-valid browser session rather than
mislabeling it expired. No private snapshot is cached or rendered on that screen.
Actual invalid/expired/revoked capabilities still close the session. A failed reply
retains text when the current snapshot remains readable, but files must be selected
again. For an uncertain response, the screen tells the user to inspect the history
before resubmitting.

Existing V10 route/profile/flag composition suffices; **no new shared wiring or
migrations**. Add `apps.requester_portal.workflow_tests` to the focused campaign
labels; the affected `apps.requester_portal.browser_tests` now exercises one-step
clarification with a file and writes `.local/qa/v11-requester/browser/` artifacts.
See [V11_REPORT.md](V11_REPORT.md) for exact evidence and remaining pilot limits.

## Optional content reporting

When the separately guarded `apps.content_reports` feature is enabled, this portal
offers a native report form for the currently authorized answer and its exact
parts. It sends the report to human review and shows a minimal receipt; it does
not modify the answer or treat report receipt as repair. Staff review notes stay
out of the requester projection. See `apps/content_reports/README.md` for version
pins, authorization, idempotency, lifecycle and verified scope.
