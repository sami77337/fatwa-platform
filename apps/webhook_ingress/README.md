# Webhook ingress — restricted, synthetic preview

**NOT_DEPLOYED / Gate B NOT_PASSED.** This is a provider-authenticated
*receipt capture*, not an external account connection, a case/evidence binding,
a live subscriber or a sender. This new source is deliberately independent of
the old interrupted webhook agent commit, which was not retrievable from GitHub
during this recovery.

## Implemented boundary

- Existing \`CaseworkGuard\` admits only literal loopback requests under
  \`/casework/webhooks/<configured UUID>/\`, with the original durable rate
  budget, request-byte limit, database ownership and maintenance guard unchanged.
- Every account UUID has one explicitly configured synthetic \`SourceContext\`.
  An unknown, invalid, or real/non-synthetic profile is closed, not guessed.
- Meta: require \`X-Hub-Signature-256: sha256=<64 hex>\`, verify HMAC-SHA256
  against the **original request.body**, compare in constant time. A standalone
  GET verification checks all three \`hub.*\` values, rejects duplicates and
  echoes only a bounded decimal challenge after the token matches.
- Telegram: require the exact configured
  \`X-Telegram-Bot-Api-Secret-Token\` on POST (never claim HMAC for Telegram).
  No Telegram GET verification.
- No credentials, raw bodies, sender IDs or phone numbers are deliberately
  placed in URLs, logs or responses. Meta verification mandates the
  `hub.verify_token` query parameter for a one-time subscription handshake:
  reverse proxies must redact that field from access logs. The receipt is
  committed before a 200; a failed write returns 503 so the provider may retry.
- Signed **single** Meta events are conservatively projected as Facebook Page
  feed comments, Messenger DMs, Instagram DMs and WhatsApp Cloud text messages.
  The account/page/WABA identifier is checked against the server-owned context.
  Multiple events, edits, echoes, media, statuses and ambiguous sources remain
  immutable original-byte receipts with an explicit review reason; they do not
  fabricate a question or attachment.
- The historical PostgreSQL insert trigger originally listed only the old
  three source types. Migration `source_case_intake.0005_meta_source_guard`
  expands *only* the whitelisted synthetic provider names without dropping
  SHA-256, raw-size, immutable-ledger, account or evidence guards. Reversal is
  blocked if Meta receipts still exist rather than silently losing their use.
- The existing staff source inbox now has distinct Facebook, Messenger,
  Instagram and WhatsApp filters. Current independent review permission is
  still required for every unbound receipt, including raw original access.
- The transport invokes \`source_case_intake.capture\` only, **never**
  \`process\`, \`ingest\`, \`resolve_review\`, a Mufti approval, or publication.
  Existing unique event/raw digests retain replay/conflict behavior. Staff
  processing needs the pre-existing explicit review/case rights and follows the
  canonical evidence history independently.

No provider accounts or credentials are provisioned here. The feature flag and
profiles remain \`False\`/\`None\` in the campaign settings. Even configured
fixtures are restricted to \`synthetic-\` accounts and loopback. This is **not**
a production webhook listener; it does not make Meta subscriptions live, nor
does it implement batches, media retrieval, Facebook/WhatsApp outbound channels
or provider status reconciliation. Production requires an independently approved
private-store/retention model, account permissions, keys, provider proofs,
operational topology and non-loopback HTTPS ingress.

## Explicit synthetic example

Use a unique UUID route key (never a source account credential) and set via an
isolated test settings overlay, **not** by editing production defaults:

\`\`\`python
FATWA_SOURCE_CASE_INTAKE_ENABLED = True
FATWA_WEBHOOK_INGRESS_ENABLED = True
FATWA_WEBHOOK_INGRESS_PROFILES = {
    "11111111-1111-4111-8111-111111111111": {
        "source": "messenger",
        "account": "synthetic-page-account",
        "conversation": "synthetic-page-id",
        "secret": "a"*40,
        "verify_token": "b"*40,
    },
}
\`\`\`

The exposed route only records authenticated source bytes. The separately
authorized \`source_case_intake.services.process\` performs the later
human-controlled case/evidence operation; it is not called from a webhook.

## Source specifications (retrieved 2026-11-21)

- [Meta webhook handshake, raw-body signature and retries](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/)
- [Meta Page feed comment fields](https://developers.facebook.com/docs/graph-api/webhooks/reference/page/)
- [Meta webhook permissions and development-mode behavior](https://developers.facebook.com/docs/graph-api/webhooks/)

Fixture tests are not evidence of a real provider delivery. Run the dedicated
\`Meta and Telegram signed intake\` workflow on PostgreSQL 17/18; keep the
functional-completion registry and existing 55 browser journeys unchanged
until a reviewed candidate and fresh full-head acceptance are registered.

## Additional protected Chromium journey

`apps.webhook_ingress.browser_tests.SignedMetaBrowserTests` is a real
sandboxed Chromium test on **both** isolated PostgreSQL majors in the dedicated
signed-intake workflow. It submits a cryptographically signed synthetic Meta
payload over HTTP, verifies bounded exact replay and rejected forged signature,
logs in through the actual staff route, filters the immutable receipt, opens the
original text and downloads the original bytes, checks Arabic RTL/overflow at
320px and 1280px, then withdraws the separate source-review grant and verifies
the previously visible event disappears. Two screenshots and a Playwright trace
plus success-only `result.json` are required for each major. Do not credit this
journey until actual GitHub Actions and the downloaded archive have passed.
The existing 55-journey functional scope is unchanged; this is an additional
independent browser gate, not a substitute for the whole exact-head receipt.

## WhatsApp account/phone scoping

A WhatsApp Cloud webhook carries both the WABA ID (`entry[].id`) and the
business phone ID (`changes[].value.metadata.phone_number_id`). These are
**distinct** values. In a synthetic `FATWA_WEBHOOK_INGRESS_PROFILES` profile,
WhatsApp additionally **requires** a server-owned `phone_number_id` key. The
entry ID must match the configured `conversation` WABA, and the metadata phone
must match the configured `phone_number_id`. The payload must also declare
`messaging_product=whatsapp`. Signed events for a different phone under the
same WABA are stored as immutable held receipts for independent human review,
not silently bound to the configured sender or case. Other providers must not
supply this phone key. No real phone number or WABA is provisioned in the
current closed fixture profile. Meta's published Webhook envelope distinguishes
these fields; see its maintained [WhatsApp Cloud API reference](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api).

## Instagram media comments (distinct from direct messages)

Meta documents the `instagram` `entry[].changes[]` `comments` field with
`value.id` (comment ID), `value.from.id` (Instagram-scoped sender),
`value.media.id` (media owner context) and `value.text` (original text).
The single-event parser retains the exact original signed bytes, preserves
the comment ID and sender, and derives an isolated conversation identifier
from the configured professional-account ID **and** the media ID. Repeated
titles, usernames, or comments on different media cannot become shared
conversation rights. It accepts only the documented `comments` subset;
`live_comments`, mentions, multi-entry notifications, missing media IDs,
account-self events and comments with `parent_id` are held for independent
review. A parent comment is not automatically declared a canonical follow-up
or added to any existing case. Staff must use the separate authorized case
processing and review APIs.

Sources: [Meta Instagram webhook field reference](https://developers.facebook.com/docs/graph-api/webhooks/reference/instagram) and [Instagram webhook setup and required permissions](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-instagram/).
A passing synthetic test proves only the supported parser and local
authorization boundary; it does not attest live `instagram_manage_comments`
approval, installed Page subscriptions, real account credentials, or delivery
from Meta. The protected Chromium workflow now tests one signed single-event
Instagram media comment alongside Messenger replay, and requires exact
downloaded original bytes for both. The 55 existing product journeys are
unchanged and remain separately required.
