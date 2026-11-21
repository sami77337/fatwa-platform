# Private technical media derivatives — bounded continuation

Development only. Disabled by default. No production activation, main merge,
public release, AI transcription provider, or scientific review is inferred.

## Recovered contract and exact remaining scope

| Owner | Original contract | Preserved existing implementation | This continuation |
|---|---|---|---|
| 382 | SPEC-U11-009, SPEC-U11-011; D-031 | Exact attachment/answer/library originals, manual transcript history, separately released public media | Durable, independently authorized THUMBNAIL and AUDIO_PLAYBACK jobs; real local ffmpeg; immutable derived bytes, provenance, retry/cancel |
| 441 | SPEC-U02-014, SPEC-U11-009; D-016, D-055 | RecordingTranscript and its human review/edit history remain separate from AnswerPart | No worker writes, replaces, deletes or auto-selects a transcript, answer, citation, decision or publication |
| 432 | SPEC-U15-013; related SPEC-U11-025, D-038 | Original audio remains readable through its existing current authorization boundary | Technical processing failure retains originals and usable independent results. Actual ASR remains unavailable; this does not prove transcription quality or a working ASR integration |

Sources: `docs/product/v12_scope_evidence/specifications.json` (match exact
`original_id`), `docs/product/functional_continuation/audit_operations_375_556.json`
(owner `original_id`, not its different parsed index), and
`docs/product/v12_scope_evidence/sources/decision_log.json`.

Only owner **382** is a candidate for new credit in this continuation, after
exact integrated service/browser/restore evidence. Owner **441** is a regression
invariant, not additional completion: although it is not in the previous
57-point list in `functional_completion/scope_plan.json`, the confirmed anchor
`ac8f5170b82767d759bd656fe9c2ea33cf48fc9f` already has separate
`public_answer_media.RecordingTranscript` rows referencing `AnswerPart`, immutable
previous versions/source pins and human review. Its
`test_exact_revision_review_release_optional_transcript_and_segments` explicitly
preserves `AnswerPart.original`, and
`test_new_meaning_revision_loses_review_and_preserves_first_and_public_exact_pin`
preserves the earlier reviewed transcript. Its existing protected browser method
`test_native_transcript_revision_review_public_playback_seek_and_withdrawal`
already exercises those versions. Rechecking that behavior while introducing a
technical worker does not create another owner-point completion. Owner **432**
remains partial because no actual ASR provider is integrated.

Recovery inspection found existing validators in `apps/private_media/worker.py`
and `video_worker.py`, a bounded ephemeral selected-PDF-page worker, durable
export-specific jobs, `RecordingTranscript`/`PublicMediaEdition` histories, and
FAST8's explicitly synthetic manual segment queue. No later saved persistent
thumbnail/transcoding/ASR worker was found in available refs/worktrees. These
existing functions are reused rather than replaced.

## Proposed finite execution contract

* Only exact `ATTACHMENT`, `ANSWER_PART`, or `LIBRARY_VERSION` sources, within
  the actual currently authorized case. No URL, path, arbitrary command, media
  filter, model name, or executable comes from a browser or job row.
* Only two technical recipes: a first-frame, aspect-preserving PNG thumbnail,
  and a complete PCM16 WAV playback copy retaining the source sample rate and
  channel count. There is no clipping, concatenation, speech generation,
  denoising, text generation, resampling or automatic publication.
* READ/source rights, classification, clean current source scan, current staff
  identity and separate explicit derivative grants are all required. Successful
  work is not an enduring access grant. Original and derivative downloads repeat
  these checks; final pure pins survive final HTTP/session callbacks.
  Every derivative permission also supplies `grant_deadline` for the exact same
  actor/action/task/source: a future timezone-aware datetime no more than one
  hour ahead. Missing, naive, expired or unbounded dates are denied. The scope
  keeps the minimum of every grant it used, including a short READ followed by a
  longer DOWNLOAD. A later callback or a valid actor/session cannot extend it.
* Request, event history and result are separate append-only PostgreSQL rows.
  Each result binds exact source owner/version/hash/size, recipe version, actual
  executable/probe identities and output hash/size. Case ownership is never
  deduced from byte deduplication.
* A claim uses a finite lease and attempt. CPU processing occurs after its
  authorization transaction closes. Fresh authorization and lease/cancel checks
  occur before committing any result. Explicit retry creates another attempt;
  stale or cancelled workers cannot save or return a late result.
* Browser requests enqueue and inspect work. A separate finite management
  command uses an explicitly configured directory and EXECUTE policy for the
  original submitter, resolving current identity each time. It does not create a
  system principal or reuse an expired request-bound session lease. A recorded
  origin session is an additional revocation veto, never a background grant.
* Input remains within the existing 192000-byte validated-original contract.
  Child wall/CPU/memory/output and process concurrency are bounded. Audio output
  above its fixed bound fails instead of silently truncating it. Local binaries
  run with a minimal environment, pipe-only protocols and no user arguments.

### Permission and execution bounds

| Contract | Bound or required independent permission |
|---|---|
| Exact derivative grant | `grant_deadline` uses the same provider/subject/epoch/case/action/task/source as `permits`. A timezone-aware datetime must be strictly later than the current time and no more than one hour ahead. There is no minimum grant duration. |
| Missing or invalid expiry | A missing method/date, non-datetime, naive datetime, expired date or date over the one-hour bound is denied. Actor/session validity is never a substitute. |
| Multiple permissions in one response | Keep the earliest previously used grant, actor and original-source deadline through all callbacks and the final pure pass. A later, longer grant cannot extend it. |
| READ | Independent derivative READ plus current original READ, privacy READ, clean current original scan and actual current identity/session. A completed job or signed ticket grants none of these. |
| DOWNLOAD | All READ requirements plus derivative DOWNLOAD, privacy EXPORT, and source export permission (Library DOWNLOAD or case-media EXPORT_MEDIA). Its longer expiry cannot extend an earlier READ. |
| Queued execution | At most ten minutes from creation and no later than the earliest retained grant/identity/source deadline. Current EXECUTE, session and MFA vetoes are checked again before and after work. |
| Current claim | At most sixty seconds, also bounded by the job execution deadline. Explicit retry requires current authority; at most four attempts. |
| Decoder | One process slot and one database-wide current lease; child wall bound fifteen seconds with separately bounded version probes and decoder calls. This is separate from grant/session time. |

## External dependencies and honest residual gaps

A real ASR provider/model, its authorized processing policy, task extension of the
central AI gateway, deployment credentials, language/quality evaluation, and
human review remain absent. `CITATION_CANDIDATES` is the gateway's only admitted
AI task; this app must not introduce an alternate transcription gateway. The UI
must state automatic transcription is unavailable while the existing manual
transcript workflow remains intact. An unavailable provider is not a PASS for
owner 432, and a queue alone is not completion of 382/441.

This private technical recipe does not cover semantic/public redaction review,
large-file/object-storage production topology, worker autoscaling, an ASR vendor,
or final visual design. Existing public-release gates stay independent.

FFmpeg command semantics are checked against its primary documentation:
https://ffmpeg.org/ffmpeg.html,
https://ffmpeg.org/ffmpeg-protocols.html,
https://ffmpeg.org/ffmpeg-filters.html.

## Integration checkpoint (not a full acceptance receipt)

Implemented app files now provide the three sealed tables, SQL source-owner and
state/lease guards, independent finite `process_media_derivative` command, two
actual recipes, native forms and private output view. The processor must be
explicitly selected as `FFmpegProcessor('/usr/bin/ffmpeg', '/usr/bin/ffprobe')` in a
development-only server profile; absent configuration records UNAVAILABLE. The
worker directory must be the actual configured current identity directory and
still needs the exact independent EXECUTE grant for the stored submitter.

Original files remain under the existing scan ledger. A derived output is not an
uploaded source or a new input admission: it is emitted only by the fixed local
PNG/PCM recipe, separately validated, sealed by the output hash, and every use
also re-admits its exact source's current clean receipt. It cannot enter source
intake or replace an original, and is never made public by this app.

Shared wiring (coordinator-owned): install `apps.media_derivatives`; the four
`FATWA_MEDIA_DERIVATIVES_*` settings shown in `settings.py` stay False/None;
include the two native paths from `urls.py` before campaign patterns; add
`apps.media_derivatives.policy.DerivativeResponses` after SessionContext while
keeping MaintenanceGuard first. Admit the exact workspace GET/HEAD/POST route
and exact output UUID GET/HEAD route in CaseworkGuard. Register the latter in
`private_media.links.ROUTES` as `media_derivatives.DerivativeJob`, `case_id`, with
the derivative-enabled reader flag. Retained pure guards follow all domain and
final session callbacks. Missing signed-route wiring remains closed.

The finite command is:

```
python manage.py process_media_derivative --job <saved-job-uuid> --synthetic-fixtures-only
```

or `--limit 1` through `--limit 10`, with the explicitly configured directory.
There is no infinite worker loop, implicit automatic retry, provider selection,
production activation or background principal invented by this command.

Verified at the first code checkpoint: 10 standalone real-ffmpeg/bounded-child
checks passed; 13 PostgreSQL 17 job/denial/immutability tests passed (18.609s).
Library/video/transcript-preservation, combined privacy/session, native browser,
PostgreSQL 18 and fresh-target recovery proof remain to be completed. These
counts are a checkpoint and do not close owner 382, 441 or 432.

## Verified development checkpoint

The complete eight-class service/HTTP/process group passed on PostgreSQL 17 and
18: **40/40** on each (74.628s / 74.994s). This includes actual ffmpeg video and
non-square-pixel aspect handling, all three owned source families, full audio
channels/sample count/tail, existing reviewed transcript/public pin preservation,
exclusive leases and explicit finite retry, native signed GET/HEAD/Range,
independent source export + derivative DOWNLOAD, and final real Session USE
callbacks revoking source READ, source classification or current scan.

Inline READ does not imply a download grant. A derivative download additionally
requires DerivativeAuthority.DOWNLOAD, current original READ, classification
EXPORT, and the existing source-specific export permission: Library DOWNLOAD or
ExportAuthority.EXPORT_MEDIA for case attachments/answer parts. The native
button is rendered only under that current permission.

The recovery helper `apps.media_derivatives.recovery_support` declares three
nonempty tables, `media_derivatives_history_guard()`, three matching triggers and
14 named denials. It creates an actual local-ffmpeg result and preserved
CANCELLED/UNAVAILABLE histories; restored reads require fresh current trust and
never invoke ffmpeg or a scanner. Its local helper contract passed. Independent
fresh-target restore remains aggregate-runner evidence.

The MFA follow-up is verified against the actual campaign composition at parent
`2799046`: six focused `test_mfa.DerivativeMfaTests` passed on PostgreSQL 17 and
18 (30.627s / 30.518s). The RED test first proved that a revoked factor could
reach the processor. The worker now captures the exact saved SessionAssurance
and Factor, repeats the independent MFA USE permission before claim and after
processing, and retains pure proof/factor/expiry checks after every final
callback. It creates no proof or request lease. A disabled or omitted MFA app
cannot ignore saved factor history. Native tests use real password/TOTP issuance
for fabricated accounts, not manufactured assurance rows; factor revocation
before claim, after actual ffmpeg, or during the final Session USE callback
prevents a result. MFA never grants source READ or derivative EXECUTE.

Protected hosted browser and aggregate fresh-target evidence remain pending; no
ASR completeness is claimed. Local protected Chromium launch is blocked before
navigation by the executor's `socket() ... Operation not permitted`; browser
security remains enabled and that attempt is not a PASS.

## Exact aggregate integration contract

The service labels are `apps.media_derivatives.test_execution`, `test_jobs`,
`test_existing_sources`, `test_http`, `test_privacy`, `test_recovery`, `test_mfa`
and `test_deadlines` (each with the same `apps.media_derivatives.` prefix). They
contain 48 tests in ten explicit classes: `RealFFmpegExecutionTests`,
`BoundedDecoderProcessTests`, `DerivativeJobTests`, `LibraryDerivativeTests`,
`HumanTranscriptPreservationTests`, `NativeDerivativeTests`,
`DerivativePrivacyTests`, `DerivativeRecoveryTests`, `DerivativeMfaTests` and
`DerivativeGrantDeadlineTests`. The preceding unified app head
`b3c33145d6c98c3e6144bcd5e5971d392c382c40` passed all 46 existing tests on
PostgreSQL 17/18 (122.852s / 121.494s). A subsequent explicit-expiry RED test found
that 206/200 bytes could survive after a short derivative READ expired during
the final real Session USE callback. The new required grant deadline fixes that
gap and adds the two tests; it must receive its own exact-head verification.

The protected native browser identity is
`apps.media_derivatives.browser_tests.MediaDerivativeBrowserTests.test_native_queue_retry_original_playback_download_cancel_and_revocation`.
It uses the actual campaign URL configuration and middleware, one actual
server-governed synthetic session, real forms/CSRF, an independent finite worker
command and actual ffmpeg. It starts at the real “مهام الوسائط” navigation link,
records UNAVAILABLE, opens the saved original, explicitly retries, plays the
complete audio through native controls, downloads exact playback bytes, generates
and decodes a real 320×160 PNG thumbnail, cancels a new queued job, then rejects
the old signed output URL after source READ or source scan revocation. Fresh
Range/HEAD reads succeed again only after both permissions are restored.
Transcription remains explicitly unavailable. Synthetic scanner fixtures are
identified; this proof does not replace the independent actual ClamAV receipt.

The browser writes under
`.local/qa/functional-continuation/media-derivatives-browser/`:

* `result.json` has `status=PASS`, `sandbox=true`, `protected_browser=true`,
  `widths=[320,1280]`, `native_actions=true`, `actual_ffmpeg=true`,
  `original_bytes_preserved=true`, `canonical_histories_unchanged=true`,
  `unavailable_original_opened=true`, `explicit_retry=true`,
  `explicit_cancellation=true`, `source_bound_outputs=true`,
  `positive_reads_after_denial=true`, `actual_session_origins=true`,
  `actual_asr_provider=UNAVAILABLE_NO_PROVIDER`, `scanner_mode=SYNTHETIC`,
  no external requests/page errors, actual engine/source/output hashes, and
  the two named browser denials `source-read-revoked` / `source-scan-revoked`.
* `trace-staff.zip`, `playback.wav`, `thumbnail.png` and diagnostic
  `progress.jsonl` / `stacks.log` accompany the receipt.
* Screenshots at both 320 and 1280 widths are `queued`,
  `unavailable-original-preserved`, `ready-native-playback-download`,
  `ready-native-thumbnail`, `cancelled-original-preserved`,
  `source-read-revoked` and `source-scan-revoked` (each `-<width>.png`).

`apps.media_derivatives.recovery_support` declares the three nonempty tables
`media_derivatives_derivativejob`, `media_derivatives_derivativeevent`,
`media_derivatives_derivedoutput`; function `media_derivatives_history_guard()`;
and triggers `media_derivatives_job_guard`, `media_derivatives_event_guard`,
`media_derivatives_output_guard`. Its 14 exact named denials are
`derivatives_disabled`, `missing_derivative_authority`, `missing_current_directory`,
`revoked_derivative_read`, `revoked_original_read`, `missing_current_scanner`,
`changed_scan_signatures`, `disabled_scan_with_saved_original`,
`expired_current_identity`, `foreign_case_identity`, `cross_actor`, `wrong_job`,
`cancelled_not_ready`, `unavailable_not_ready`. Restore reads validate preserved
output/provenance without running a decoder or scanner, deny each of those
changes, then succeed under restored current trust without changing any ledger.
