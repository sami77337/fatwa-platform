# Human-authored YouTube reference — original point 73

This development-only extension implements original 73, “يمكنه إضافة رابط
YouTube.” Its direct contract is SPEC-U02-011 / D-008; SPEC-U11-012 keeps an
external reference distinct from an owned video. `NOT_DEPLOYED / GATES_HOLD`.
It does not activate a channel, publish a video or establish source availability.

## Actual behavior

The native multipart editor accepts an optional YouTube URL and a human label.
An authenticated currently scoped Mufti saves a new canonical answer revision
containing TEXT followed by retained parts, uploaded files and new link parts.
Links can be retained, reordered or excluded in later revisions. Old originals,
manifests and approvals remain historical; a new revision inherits neither human
approval nor private requester release.

The currently supported input forms are HTTPS YouTube watch URLs with only the
`v` parameter, and HTTPS `youtu.be/<id>` URLs. The ID is exactly 11 ASCII letters,
digits, underscore or hyphen. Other hosts/schemes, credentials, fragments,
additional parameters, whitespace and encoded IDs are refused explicitly. The
native form states these accepted forms. No network request is made to YouTube.

`AnswerPart.kind=YOUTUBE_LINK` stores the exact submitted URL UTF-8 bytes, their
SHA-256 and size. The MIME is `text/uri-list`; its generated filename is
`youtube-<id>.url`. The exact metadata schema is:

```json
{
  "external": true,
  "provider": "YOUTUBE",
  "video_id": "aB3dE6gH9_k",
  "url": "https://www.youtube.com/watch?v=aB3dE6gH9_k",
  "label": "Human description",
  "availability": "UNVERIFIED"
}
```

The normalized watch URL is derived metadata; it never replaces the submitted
bytes. SQL and runtime verification bind metadata, original bytes, ID, generated
filename and MIME. All existing manifest hashes include these fields. Approval
validates the URL itself without pretending to parse downloaded video. The
external reference remains inline; it is not a filesystem media object.

Staff and authorized requester pages display a labeled external anchor with
`noopener noreferrer external`, plus an explicit unverified-content statement.
There is no video embed, autoplay, availability probe or downloader. The existing
authenticated file route returns a plain-text reference attachment containing
the original URL, never video bytes. Current case/source identity, separate
private release and tracking capability remain required.

## Integration

Default-off setting: `FATWA_ANSWER_LINKS_ENABLED=False`.
The existing `save_multipart_answer` accepts `links=()`; each entry is exactly
`{"url": ..., "label": ...}`. Existing DTO keys and action names remain unchanged.
The native `answer_media_save` optionally accepts both `youtube_url` and
`youtube_label` while the feature is enabled. No new route is needed for point 73.

Shared composite delivery must map `YOUTUBE_LINK` explicitly as an external
reference. It must not treat `text/uri-list` as video, fetch content or invent
provider availability/delivery evidence. Unsupported channels retain a visible
human-action requirement. That shared change belongs to the integration lane.

New editor compositions require the existing pure atomic identity snapshot
capability. The native command and rendered response share a guarded transaction;
actual storage locks are acquired before the outer database unit. A late identity,
configuration, source or capability change denies the response and rolls back its
command. Normal file-only legacy behavior and media storage contracts are retained.

## Evidence and bounds

The focused new/native tests and existing answer/storage regressions passed
**36/36 on PostgreSQL 17 (29.320 s) and 18 (29.098 s)**. Test modules:
`apps.answer_media.test_youtube`, `apps.answer_media.tests`,
`apps.answer_media.tests_storage`. Logs are
`.local/qa/youtube-final-pg17.log` / `youtube-final-pg18.log`.

The additional recovery adapter is `apps.answer_media.youtube_recovery_support`.
It creates actual link/manifest/private-release rows through services, returns
exact source pins, and verifies a restored URL plus missing-directory and
inactive-identity denials before another successful read. It uses the already
inventoried answer tables; it introduces no new tables or byte-owner registry.
`apps.answer_media.test_youtube_recovery` exercises that adapter locally.
After the final strict JSON-type guards, the recovery and forged-metadata pair
passed on PG17 (0.475 s) and PG18 (0.518 s). These overlap the main gate and add
one distinct recovery test, giving 37 distinct tested methods across these runs.

Protected native journey:
`apps.answer_media.browser_youtube.YouTubeAnswerBrowserTests`.
Success-only receipt:
`.local/qa/functional-continuation/youtube-answer-browser/result.json`, with
320/1280 screenshots and a trace. The journey saves the link in the native editor,
uses the ordinary human approval and separate private-release forms, opens it
through the requester session and proves revoked access denies the original URI.
External network requests are blocked and must remain zero. Hosted protected
browser proof is pending; the known local protected Chromium OS block is not
bypassed or counted as a pass.

This change claims only point 73. It does not claim the related-material side panel,
synonym dictionary, shadow search, YouTube content ingestion or public publication.
