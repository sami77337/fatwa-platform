# Owner point 383 — scoped temporary private media links contract

Preparation base: `44495bf8e80c685955e813cf214a342bf235bd67` (PR 244).
The implementation is saved in `eef7c90`, its separate guard/settings wiring in
`7a140a2`, and its recovery helper in `70acf0e`. It remains disabled by default.
PostgreSQL service/HTTP evidence is recorded below. Browser and aggregate encrypted
restore proof must pass on the exact integrated commit before whole-point credit.

## Source and scope

- Original 383: private files are served by temporary signed links.
- SPEC-U14-018 requires current verification, temporary access according to policy,
  separation of environments and secrets, and no inferred redistribution right.
  Link revocation and lifetime are executable details; already downloaded external
  copies cannot be withdrawn by this mechanism.
- D-037 requires object-level checks on every request and revocable sessions.
- In-scope private surfaces: case attachments, answer parts, research-library file
  versions and private original/transcript recording playback. Citation original
  and page/audio derivative byte routes are included in the closed inventory below;
  public independently released copies retain their separate release gates.

## Exact byte route inventory

`<id>` is the canonical lower-case UUID of the existing immutable source row.
Eight route patterns cover fifteen concrete route forms. Every alias has its own
ticket binding and retains the original domain's current authorization.

| Canonical route | Exact source | Purpose and current boundary |
| --- | --- | --- |
| `/casework/{staff,status}/attachments/<id>/` | `CaseAttachment` and original bytes | INLINE or DOWNLOAD; existing case/requester attachment permission |
| `/casework/{staff,status}/answer-media/<id>/` | `AnswerPart`, manifest, current answer and original bytes | INLINE or DOWNLOAD; existing staff scope or current explicit requester release |
| `/casework/staff/library/<id>/{file,download}/` | `LibraryVersion`, item and original blob | INLINE on `file`; DOWNLOAD only on `download` with independent current DOWNLOAD grant |
| `/casework/staff/recording-parts/<id>/audio/` | Original `AnswerPart` | INLINE; current private recording permission |
| `/casework/staff/recording-transcripts/<id>/audio/` | `RecordingTranscript` and its original part | INLINE; exact transcript version and current private transcript permission |
| `/casework/staff/timed-citations/<id>/{audio,review-audio}/` | `TimedCitation` and original audio | INLINE; confirmed/review reader keeps its own current source and review checks |
| `/casework/staff/pdf-citations/<id>/{document,review-document,page,review-page}/` | `PdfCitation`, original PDF or exact selected-page bytes | INLINE; original/page and confirmed/review paths cannot exchange tickets |
| `/casework/precise-citations/sources/<id>/file/` | `CitationAnchor` and its exact library source version | INLINE; current case, answer-use, citation and source rights |

Native emitters include answer parts, attachment desks, the requester portal,
Mufti sidebar, source-intake linked files and evidence timeline, research library,
private recordings/segments, timed/PDF desks and the precise citation source page.
The HTML segment fragment stays outside the signed server path and is preserved;
the original audio byte route still requires its bound ticket and current rights.

Public byte routes serve independently released copies through existing public
publication gates. They do not become private URL grants. Native POST operation
responses (selected exports, delivery exports, raw source-event downloads and
operational-workspace listening) are independently CSRF/operation-authorized and
do not expose reusable GET byte URLs. They remain operation responses, outside
this GET/HEAD/Range locator inventory. Adding any future private byte route requires
an explicit route, source model, native issuer and current-reader hook.

## Contract

The new development capability is disabled by default. While it is enabled,
private byte endpoints require a single bounded `access` query ticket in addition
to the current staff/requester session and each domain's current source rights.
Bare UUID URLs stop working in that mode. Possession of the URL is never a grant.

Tickets bind the canonical local byte route, audience, exact immutable source
version and digest, read/download purpose, authenticated principal/epoch and the
issuing browser-session proof. Do not encode a raw requester token, cookie,
credential, question, answer, filename or user identifier in a URL. Use a keyed
digest for identity/session bindings. A different object with identical bytes,
another browser for the same account or a different purpose cannot reuse a ticket.

Explicit development configuration:

- `FATWA_PRIVATE_MEDIA_LINKS_ENABLED=False`
- `FATWA_PRIVATE_MEDIA_LINKS_KEY=None` (separate configured signing secret)
- `FATWA_PRIVATE_MEDIA_LINKS_EPOCH=None` (explicit revocation/configuration epoch)
- `FATWA_PRIVATE_MEDIA_LINKS_TTL_SECONDS=None` (tests explicitly choose 120 seconds)

The development environment must have `FATWA_PRODUCTION=0`. A configured signing
key must contain 32–512 characters and differ from Django's `SECRET_KEY`; epoch
format is bounded, and TTL must be an integer from 1 to 900 seconds. These are
implementation limits, not an approved production lifetime. The expiry is also
bounded by the current authenticated session deadline.

Reject missing or malformed configuration and excessive lifetimes; never fall back
to an unsigned response. Key/epoch rotation, session expiry/revocation, lost case
scope, source permission withdrawal or superseded requester answer must invalidate
use. No fallback to retired signing keys. No new schema, cloud storage or network.

Every GET, HEAD and Range request still invokes the existing authorized domain
reader. Range parsing follows authorization, so an invalid range cannot disclose
the size of a forbidden object. Single bounded byte ranges are supported; malformed
or multipart ranges have no body. HEAD has no bytes but retains current authorization.
Authorization and exact source/configuration checks remain active until response
construction is complete. No 304/cache response bypasses them.

Successful responses preserve original bytes and restrictive no-store/no-referrer,
content-type and sandbox headers. Refusals expose no filename, digest, ETag or file
size. Native forms remain CSRF protected; downloading a private attachment issues
a short-lived current-session URL rather than sharing a bearer capability.

## Integration and final projection checks

No app installation, migration, route addition or schema is required. The template
tag lives inside the already installed `answer_media` app. The coordinator reviewed
the limited `CaseworkGuard` and campaign-settings wiring as a separate commit;
aggregate receipt and recovery-verifier integration stay coordinator-owned.

The global guard change must admit only one bounded `access` query parameter on
the exact private byte-route inventory while the feature is literally enabled.
The view repeats ticket verification and domain checks; allowing the query itself
must not authorize anything. Unexpected/duplicate fields remain rejected.
The raw `QUERY_STRING` must exactly equal the canonical one-field encoding; encoded
aliases and query mutation are rejected. Neither the guard nor header middleware
strips or rewrites the incoming query. The domain reader uses an explicit cloned
GET request only after the original request has been verified.

Campaign middleware ordering is `MaintenanceGuard`, `MaterialAPIResponses`,
`PrivateMediaResponses`, then the existing middleware. Maintenance remains first.
`PrivateMediaResponses` changes privacy headers only, including guard refusals.

The ticket signer uses a separate key, salt and empty retired-key fallback list.
Its payload holds only the canonical path, purpose, version, key epoch, times,
and keyed digests of current identity/session and exact bytes/source metadata.
No current role, grant or source decision is cached as a ticket permission.

Every use obtains the existing case transaction/locks, resolves the current staff
identity or requester capability, invokes the actual authorized domain byte reader,
and compares exact body/type/disposition pins. Native domain boundaries retain pure
final callbacks in the outer private-link projection. They run after range/response
construction and every nested callback, before leaving the transaction. Metadata,
current session, configuration, source/action history and deadline changes discard
the whole response. This includes late permission withdrawal after bytes were read.

## Saved test evidence

On `7a140a2`, the real owned PostgreSQL run passed **116/116** on PostgreSQL 17.11
(191.300 seconds) and **116/116** on PostgreSQL 18.7 (192.255 seconds). Labels:

```text
apps.private_media.test_signed_links
apps.private_media.test_signed_citation_links
apps.precise_citations.test_http
apps.pdf_citations.tests
apps.timed_citations.tests
apps.research_library.test_http
apps.public_answer_media.test_http
apps.case_attachments.tests
apps.answer_media.tests
tests.casework.test_editor_profile_compatibility
```

The original RED contract had 17 methods, the disabled-feature control passed and
16 methods failed with 26 failed subtests, with zero errors. The final source-page
inventory found two missed template emitters; the additional
`test_signed_entrypoints` RED run had two methods and three failed assertions for
missing signatures. Its repaired native-page tests exercise exact bytes, separate
download purpose, same-account new-browser denial and current scope withdrawal.
After repairing those emitters, the following group passed **41/41** on PG17.11
(46.590 seconds) and **41/41** on PG18.7 (47.057 seconds):

```text
apps.private_media.test_signed_entrypoints
apps.requester_portal.tests
apps.requester_portal.workflow_tests
apps.source_case_intake.http_tests
apps.private_media.test_link_recovery
```

These local HTTP results do not imply protected Chromium passed. The local host
denied Chromium process-singleton sockets/ptrace before launch with its sandbox
enabled. No `--no-sandbox`, browser-security override or fake media response was used.

### Three independent protected-browser proofs

All live in `apps/private_media/browser_tests.py`. Each writes its own JSON and
must pass independently; a single unrelated PASS must not stand in for the three.
Paths below are relative to `.local/qa/functional-continuation/`.

| Full test identity | JSON proof | Native evidence |
| --- | --- | --- |
| `apps.private_media.browser_tests.PrivateOriginalLinksBrowserTests.test_native_requester_and_staff_media_urls_downloads_and_browser_isolation` | `private-media-links-browser/originals/result.json` | Real staff/requester login, current answer/attachment desks and actual requester portal, keyboard native audio, native downloads, other authorized browser and audience denial |
| `apps.private_media.browser_tests.PrivateLibraryLinksBrowserTests.test_native_library_playback_download_and_current_download_revocation` | `private-media-links-browser/library/result.json` | Native library/version selection, audio and original download, separate DOWNLOAD revocation while READ still works |
| `apps.private_media.browser_tests.PrivateRecordingLinksBrowserTests.test_native_recording_and_reviewed_segment_playback_then_current_rights_denial` | `private-media-links-browser/recordings/result.json` | Current recording and reviewed exact segment, native keyboard seek/playback, subsequent GET/HEAD/Range denial after transcript rights withdrawal |

Each proof requires sandbox/protected-browser true, widths 320 and 1280, real
screenshots and traces, no external requests, no page errors, and actual authorized
media HTTP responses. Browser API requests supplement native controls for bounded
range and HEAD evidence; they do not replace navigation, playback or downloads.

### Read-only recovery helper

`apps.private_media.recovery_support` owns **zero** durable tables, functions or
triggers: `TABLES = FUNCTIONS = TRIGGERS = ()`. Its `populate()` obtains a distinct
existing research-library fixture. Pins contain only `case`, `versions`, `tables`;
no session, link, key or permission is serialized. Existing source rows and blobs
remain in the library recovery inventory.

`verify_restored()` opens a fresh connection, validates exact source/history pins,
constructs explicitly supplied fresh synthetic current trust, authenticates actual
signed staff sessions, and invokes real resolved byte views for two retained
originals. RequestFactory avoids global HTTP throttle writes only; current auth,
case, source and byte reader checks remain active. Independent native login proof
belongs to the browser journeys above.

| Exact `denial_checks` key | Actual denied reads |
| --- | ---: |
| `unsigned_private_url` | 2 |
| `same_actor_different_browser` | 2 |
| `missing_signing_key` | 2 |
| `rotated_link_epoch` | 2 |
| `missing_current_identity` | 2 |
| `revoked_current_identity` | 2 |
| `revoked_current_read` | 2 |
| `revoked_current_download` | 2 |
| `cross_purpose_ticket` | 2 |

Each count is an actual denied GET Range and HEAD. The exact total is 18. Positive
original/range/HEAD reads are asserted before and after the denial sequence.
Expected receipt fields include `positive_reads_after_denial=True`,
`fresh_connection=True`, `exact_restored_private_originals=True`,
`current_browser_sessions_required=True`, `canonical_and_history_unchanged=True`,
`serialized_session_or_link_grants=False`, `new_table_count=0` and `status=PASS`.
The helper's direct test passed 1/1 on PG17 (2.127s) and PG18 (2.333s), at `70acf0e`.
That is not a substitute for the coordinator's encrypted backup/restore CI run.

## Policies not invented here

Tests select a synthetic 120-second lifetime and generated development authority;
they do not accept production TTLs, key custody/rotation operations, identity/MFA
providers, broader download/redistribution grants or final privacy classification.
Stateless tickets inherit session/source/key revocation. Individual ticket revoke
lists would require a separately specified authoritative store, and are not
silently substituted for existing current authorization.

No production policies, actual identities, classifications or owner approvals are
created here. Gate/production status is unchanged. **NOT_DEPLOYED; GATES_HOLD.**
