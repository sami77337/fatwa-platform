# Synthetic multipart answers

This app extends the canonical `Case`/`AnswerRevision`/`CaseDecision` model. It does
not create a second case, ruling, evidence stream or delivery claim. Its originals
belong to a human authored **answer**, never to requester evidence attachments.

`FATWA_ANSWER_MEDIA_ENABLED=False` and `FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=False`
are default-closed integration flags. Enable only in an isolated owned synthetic
PostgreSQL environment. Only the current scoped trusted MUFTI can author a version.
The case's normal explicit human decision approves the complete immutable version;
the integration validates `manifest_for_locked_answer()` and shows its parts before
that decision. Every save clears the previous approval and creates a new version.

## Authored parts and original storage

The required human text is the first part. Add a validated file/audio part and save;
the native form can retain the latest version's existing files and append one more
file in another new version. Maximum eight ordered parts total. Choosing replacement
creates a different version; it never overwrites originals. Shared
`apps.private_media.validation.validate` enforces the V8 media allowlist and parser
limits (192000 bytes/file, text65536). No malware scanner is claimed.

`AnswerManifest` pins ordered part UUIDs, kind, MIME, original bytes' SHA-256/size,
filename and parser metadata. `AnswerPart` stores originals privately as immutable
PostgreSQL bytes (the bounded synthetic inline adapter); no static/public URL or
object-storage credential is introduced. Canonical answer identity supplies the
author/provider/epoch, answer version, facts version, decision and timestamps.
Database guards reject update/delete, late append, wrong canonical version, altered
original hash/size and incomplete manifests. New citation edits copy media into new
identities and new manifest, with the new human text. New media edits carry verified
citations forward through the citation app's same-transaction helper. Neither copies
approval or private release. The original source revisions remain intact.

## Private availability is separate from transport

Existing text-only return-to-origin transport cannot safely omit media. Parent
integration rejects such preparation with a human-action state. No sender, connector,
provider receipt or reading proof is produced here; #225 signed text delivery is
unchanged.

After approval, its **same** MUFTI (subject/provider/auth epoch) must explicitly
confirm a separate private portal release. `PrivateAnswerRelease` is append-only and
pins the exact decision, manifest and evidence version. It does not mark delivery or
reading. On every requester page/file read, the app verifies:

- current valid requester capability for that case;
- current canonical answer, facts, human approval and exact release manifest;
- release author's current trusted server identity, MUFTI role, case scope and epoch.

Missing/revoked identity or scope, new answer/citation revision, new facts or revoked
requester capability closes access even if the historical release row still exists.
No old artifact UUID bypasses this check. Staff file reads independently recheck
current scoped identity. No browser field supplies identity/role/provider.

## Integration contract

Register `apps.answer_media`. Staff actions `answer_media`, `answer_media_save`,
`answer_media_release` dispatch to `views.staff`; entry takes `case_ref`. Requester
POST action `answer_media` dispatches to `views.requester` using only its capability.
GET/HEAD routes (no query strings) are authenticated byte selectors, not public links:

- `/casework/staff/answer-media/<uuid:part_id>/`, `views.staff_file`, named `answer_media_staff_file`.
- `/casework/status/answer-media/<uuid:part_id>/`, `views.requester_file`, named `answer_media_requester_file`.

Parent owns guard route patterns, private cookie path coverage, no-store/nosniff,
strict file CSP preservation and HTML `img/media/frame 'self'` policy. Byte responses
are bounded complete responses; Range support is not claimed. Use
`answer_media/parts.html` with `package={text,parts}` and `is_staff` to preview all
parts before approval. URL paths retain authorization checks; rendered IDs are not
capabilities.

Service entrypoints: `save_multipart_answer`, `staff_snapshot`, `staff_read`,
`release_private`, `requester_snapshot`, `requester_read`. Internal caller-locked
helpers: `manifest_for_locked_answer(answer)` and
`clone_parts_for_new_answer(previous, answer)`; both are deliberately flag-independent
so disabled editing never stops validation of existing immutable records.

## Focused verification

`apps.answer_media.tests` runs on real PostgreSQL17/18. It covers compound text/audio/file,
native multipart form/CSRF, immutable bytes/late inserts/rollback, version invalidation,
foreign requester and retained-part rejection, role/scope/epoch/active-state withdrawal,
requester revocation, separate private release, and populated guard migration reversal.
The isolated HTTP test admits only its exact fixture GET paths into the existing guard;
the parent campaign supplies and tests the general exact-UUID policy and browser flow.

Required human text, one newly uploaded file per native save, eight-part limit,
bounded inline storage, complete-response audio playback and lack of a delivery media
adapter are explicit development limits. No organizer policy, production permission,
AI authorship, external send or accepted fatwa is inferred. Gate B NOT_PASSED,
C/D/E HOLD, Phase01 BLOCKED; NOT_DEPLOYED.
