# Organizer transcription and editorial review

Owner point **97**, `SPEC-U03-016` and `SPEC-U11-019`, now has a native operational
editor for the existing `RecordingTranscript` and `TranscriptAction` journals.
Actual ORGANIZER / ORGANIZER_ADMIN identities create immutable derivative versions,
record an independent editorial review or withdraw a version. A MUFTI can separately
approve a version marked `MEANING_REVIEW`. The original answer, approval and audio
remain unchanged. No model or table is added.

## Explicit admission

`FATWA_OPERATIONAL_TRANSCRIPTS_ENABLED` is false when absent; integration must
declare it false. Workspace, answer-media and public-answer-media features must
also be explicitly enabled inside the owned synthetic development environment.
The original `public_answer_media.staff_boundary` remains MUFTI-only.

The actor must have current `READ_CASE` and `READ_TRANSCRIPT_EDITOR` on the
`transcript_editor` section. Reading its case-summary state under `READ_TRANSCRIPT`
does not grant editor access. Each exact source or derivative additionally needs:

| Operational action | Exact resource | Independent domain requirement |
| --- | --- | --- |
| READ_RECORDING_TRANSCRIPT | source part or transcript | READ_TRANSCRIPT |
| EDIT_RECORDING_TRANSCRIPT | source part | EDIT_TRANSCRIPT |
| REVIEW_RECORDING_TRANSCRIPT | transcript | REVIEW_TRANSCRIPT |
| APPROVE_TRANSCRIPT_MEANING | transcript | REVIEW_MEANING and actual MUFTI |
| WITHDRAW_RECORDING_TRANSCRIPT | transcript | WITHDRAW_TRANSCRIPT |
| READ_RECORDING_AUDIO | source part | current TimedMediaRights READ_MEDIA |

`CASE_RECORDING_SOURCE` pins case ID, part ID and original SHA-256.
`CASE_RECORDING_TRANSCRIPT` also pins transcript ID and digest. The existing
AnswerMediaAuthority and TimedMediaRights remain independently required. The editor
verifies original bytes under current media rights even when rendering transcript
text; returning audio to the browser additionally requires READ_RECORDING_AUDIO.
Native audio opens from an explicit CSRF-protected POST in another tab, with a
generated safe filename, private response and no credential-bearing URL.

Grant deadlines, configured policy/directory objects and pure epochs remain pinned
through rendering or byte-response construction. All storage callbacks complete
before the final pure checks. A grant removed while bytes are assembled discards
the response. A late identity change, exact-resource denial, equal-epoch policy
replacement or unrelated row append rolls back the pending version/decision.

Canonical precise/timed citation use boundaries now return their already collected
guards as a retained bundle while preserving every existing context-exit check.
The operational adapter reenrolls their callbacks, original-byte checks and pure
pins in the same final phases. Citation dependency locks precede owned case locks
without expanding the organizer's visible case scope. A real cross-case reviewed
precise citation is tested, including revocation in either direction from the last
operational/citation callback. No annotation can be treated as absent.

## Scholarly boundary

The recorded derivative author and editorial reviewer are resolved as their actual
current MUFTI / ORGANIZER_ADMIN / ORGANIZER identity. The author of the canonical
answer and its approval still use the unchanged strict MUFTI resolver. Meaning
approval explicitly requires actor.role == MUFTI both at admission and inside the
shared private persistence primitive, regardless of any policy returning true.
Reading a meaning-reviewed derivative also resolves its approver as strict MUFTI.

An organizer can flag a proposed version for meaning review; an organizer or admin
cannot substitute an editorial REVIEW for APPROVE_MEANING. Every non-withdrawal
review is independent from the transcript author. Choosing the editorial category
is a human assertion reviewed by another person; there is no automatic semantic
equivalence detector. This unit does not approve a new fatwa or edit its original.

## Native behavior and history

The queue has a separate authorized editor index including completed cases, without
inflating pending counts. Native forms save text, an explicit change category,
reason and up to six optional exact-quote/time spans. Times are never inferred.
Exact hashes, case/evidence versions, transcript/action CAS, command IDs and strict
field allowlists protect every submission. Old command retries recheck current
access and do not duplicate a version or decision. Native review and withdrawal
keep the author, action actor, reason and complete existing history visible.

The existing Mufti transcript/segment reader can read an organizer-authored version
after valid independent editorial review. Canonical author checks and public-media
release policy remain unchanged. The editor offers no public release operation.

## Evidence integration and limits

Behavior: `apps.operational_workspace.test_transcripts` and
`apps.operational_workspace.test_transcript_sources`.
Recovery: `apps.operational_workspace.test_transcript_recovery` and helper
`apps.operational_workspace.transcript_recovery_support` (no new TABLES/FUNCTIONS/TRIGGERS).
The recovery fixture preserves two versions, editorial review, actual Mufti meaning
approval and withdrawal. Thirteen named denials exercise fresh identity, section,
exact resource, domain and media grants; a real positive transcript/audio read
follows the denials, and original/history pins remain identical.

One protected browser journey is defined in
`apps.operational_workspace.browser_transcripts.OperationalTranscriptsBrowserTests`.
Proof: `.local/qa/functional-continuation/operational-transcripts-browser/result.json`,
three actual actor traces and 320/1280 screenshots. Hosted execution is still
required; defining the journey does not establish a browser pass.

All evidence uses owned synthetic cases and generated audio. No real requester
data, account-policy administration, production role grants or release is enabled.
Detailed production permission policy remains subject to D-054/D-067 and the
existing release gates. Publication management (point 99) is separate.
