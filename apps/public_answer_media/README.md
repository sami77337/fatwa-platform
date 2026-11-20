# Recording transcripts and independently released answer audio

Synthetic development only. Default flags are false and authority is absent.
NOT_DEPLOYED; existing project gates remain on hold. No ASR, external provider,
production identity, scholarly ruling, requester access grant or automatic
publication is introduced.

## Original requirements and bounded eligibility

| Original point | Documented source | New behavior | Evidence status |
| --- | --- | --- | --- |
| 272, Audio if available | SPEC-U09-011; D-056 | Explicitly reviewed and separately leased exact AnswerPart audio on its independently approved publication, current bytes and rights checked for each response | Real service/native checks pass; protected browser pending |
| 273, Transcript if available | SPEC-U09-011; D-056 | Only the exact independently reviewed transcript selected by that media edition appears publicly; optional absent transcript is labelled truthfully | Real service/native checks pass; protected browser pending |
| 274, direct segments when available | SPEC-U09-011; D-056 | Human-entered exact transcript offsets plus documented milliseconds on the bound original; public/private segment pages use media fragments and require actual source availability | Real source/native checks pass; actual seek browser pending |
| 418, edit recorded transcript | SPEC-U11-018/019; D-029 | Authenticated durable revisions beside the actual recording, reason/actor/time history, preserved first transcript, separate meaning review, no inherited review/release | Real SQL/native checks pass; protected browser pending |
| 234, search result opens original at timestamp | SPEC-U05-015; D-018 | Contract supplied for canonical_search; old portable TranscriptLink remains text-only | Conditional on separate integrated search result and actual playback proof; not credited here |

Inventory sources are `docs/product/v14_scope_evidence/matrix.json` (556 clauses),
and the linked v12 specifications and decisions. Existing private multipart
answers, private media releases and timed citations are baseline, not new credit.
No whole-point or percentage claim is made before exact-head hosted evidence.

## Durable contracts

Four append-only tables: `RecordingTranscript`, `TranscriptAction`,
`PublicMediaEdition`, `PublicMediaAction`. SQL rejects updates/deletes, altered
seals, cross-case/source binding, malformed/null segment fields, nonconsecutive
versions/decision chains, self-review and unreviewed or non-independent releases.
The canonical Case, AnswerRevision, CaseDecision and original AnswerPart bytes
are not modified. Current case/evidence revision pins and per-series CAS serialize
concurrent writers; an exact retry is idempotent and a changed request conflicts.

Transcript revisions use EDITORIAL or MEANING_REVIEW. Both start without review;
the latter needs the explicit REVIEW_MEANING capability and a distinct current
MUFTI approver. Historical exact reviewed revisions remain explicit, including
when a newer draft exists. New drafts never inherit review or public release.
Every public edition names its exact publication, original audio and optional
reviewed transcript. Independent review precedes a different actor's finite
release (up to 60 minutes). A withdrawal never revives an earlier released edition.

`AnswerMediaAuthority` is an explicit resource/action policy seam, never a role
assignment. READ_TRANSCRIPT, EDIT_TRANSCRIPT, REVIEW_TRANSCRIPT, REVIEW_MEANING,
WITHDRAW_TRANSCRIPT, PREPARE_MEDIA, REVIEW_MEDIA, RELEASE_MEDIA, WITHDRAW_MEDIA,
PUBLIC_AUDIO and PUBLIC_TRANSCRIPT are independent. Existing `TimedMediaRights`
READ_MEDIA also governs the exact source audio. Original author, decision actor,
transcript reviewer and release actors are re-resolved in the current trusted
directory, with their recorded provider and authentication epochs.

Pure atomic identity/authority/media policy revisions are mandatory. The source
and row baseline is captured before permission callbacks, held through rendering,
and compared after final callbacks and actual-byte verification. The native POST
and following page render share one transaction: failed current authorization
rolls the command back. There is no monkeypatch of browser protections or CSP.

## UI and integration

Shared campaign wiring registers the app, all three default settings, `pm_*`
actions, exact guarded GET/HEAD routes and same-case navigation. Native actions:
`pm_open`, `pm_save_transcript`, `pm_review_transcript`, `pm_prepare_media`,
`pm_review_media`. Forms remain CSRF-protected and use existing signed-in scoped
identities. No JSON editor, case capability in URLs or private filename appears
in the public surface. All filenames are generated opaque recording names.

The optional public media boundary is:

```python
with public.publication_projection(publication_id, include_media=True) as result:
    # render result['publication'] and result['recordings'] here
    # internal result['files'] and result['media_snapshot'] are not template DTOs
    response = render(...)
```

Catch only `OptionalMediaUnavailable` for one fresh `include_media=False` read
and render. `PreviewUnavailable` remains a whole-page 404. This distinction keeps
independently valid publication text when an optional source breaks, while a
late canonical/publication withdrawal cannot be downgraded to an attachment fault.
`public_answer_media/panel.html` renders safe recordings plus an optional notice.
For an outer composition whose callbacks run after this context, retain
`result['media_snapshot']` and call `services.assert_snapshot(pin)` after those
callbacks, inside the outer owned transaction. Never reuse a failed text DTO.

Private paths: `/casework/staff/recording-parts/<uuid>/audio/` and
`/casework/staff/recording-transcripts/<uuid>/{audio/,segments/<index>/}`.
Public paths: `/library-preview/publications/<uuid>/recordings/` and
`/library-preview/recordings/<new-media-uuid>/{audio/,segments/<index>/}`.
No autoplay. Missing timing produces no synchronized text or segment links.

## Search adapter

`with services.search_projection(case_id=..., subject_id=..., provider=...,
synthetic_fixtures_only=True) as result` yields `rows` and `snapshot`.
Each row has `pin`, `text`, `label`, `segment_url`. Pins contain case ID,
transcript UUID/digest, exact part UUID/SHA256, segment index/SHA256 and start/end
milliseconds. Only reviewed real-recording segments are eligible. A preexisting
denial omits that recording; a callback-time row/policy mutation rejects the whole
projection. The outer search must retain the snapshot and call
`services.assert_snapshot` after all its own callbacks and actual rendering.
Disabled/unconfigured optional media is omitted by the search adapter, with its
configuration identities still pinned. No permission is copied into the index.

## Verification

`apps.public_answer_media.tests`, `apps.public_answer_media.test_http` and
`apps.public_answer_media.test_recovery` contain 33 real PostgreSQL tests, passed
on PostgreSQL 17 and 18 before this local
commit. They include two concurrent edits, resealed hostile SQL inserts, immutable
deletes/updates, exact retries, stale facts, current scope/epoch revocation, native
forms/cookies/CSRF, source file bytes, late withdrawal and safe independent-text
fallback. Protected browser execution and encrypted recovery are separate gates;
they are not represented as passing by these native tests.

The protected class is
`apps.public_answer_media.browser_tests.PublicAnswerMediaBrowserTests`. It writes
`.local/qa/functional-continuation/public-answer-media-browser/result.json`, four
browser traces and 320/1280 RTL screenshots. It starts from the existing public
publication page's native recording link and uses sandboxed Chromium, actual
native forms and controls, checks original WAV bytes, observes a real media
fragment seek and playback, then edits, independently reviews, releases and
withdraws a new meaning revision. No local protected-browser PASS is claimed.

`recovery_support.populate()` creates all four tables through real services and
preserves a reviewed first transcript plus an unapproved second draft. Source
audio uses the harness's existing AnswerPart storage adapter; the helper never
substitutes a new root. `verify_restored(pins)` rebuilds synthetic trust only,
checks full row/canonical hashes and original bytes, proves nine real read denials
with missing authority/provider/media rights and revoked actors, repeats positive
reads, and checks that verification changed no rows or bytes. Its SQL inventory is
one `pam_history_guard()` function and four app-specific triggers. The encrypted
fresh-process drill remains a coordinator gate, separate from the focused helper
test already passed on both PostgreSQL majors.

The final snapshot reads exact original bytes before its final pure object,
authority, identity, source-row and expiry comparisons. A regression uses a real
filesystem adapter whose final read callback revokes a right; the composed reader
must reject it even after the initial projection context has exited.
An outer multi-case reader must finish all `assert_snapshot` byte reads, then
call `assert_projection_state` for every retained snapshot before its own final
pure checks. This prevents a later source adapter callback from revoking an
earlier recording after that earlier recording's final check.

### Exact citation composition

The public reader acquires the shared exact-citation dependency graph and sorted
case locks before its first case lock. The existing preview media boundary holds
the citation answer-use coordinator through actual rendering and all final source
callbacks. The enclosing recording reader then checks its media state and base
publication state again using pure checks only. No storage or permission callback
follows these last checks. A source-side callback cannot revoke already-consumed
recording permission while returning a stale player or audio response.

`apps.public_answer_media.test_citation_integration` adds three real PostgreSQL
regressions: an exact cross-case citation with preserved original audio, a final
citation callback revoking previously checked recording permission, and native
render-time citation revocation denying the whole response. All 36 media tests
passed on PostgreSQL 17 and 18 in the disposable composition profile
`apps.public_answer_media.citation_settings`. The profile adds the citation app
without changing default authority settings or protected runtime requirements.
