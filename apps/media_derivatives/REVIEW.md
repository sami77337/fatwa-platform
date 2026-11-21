# Semantic review of the bounded private derivative continuation

## What owner 382 gains

The exact owner statement is “مشتقات مثل Thumbnail أو Transcript أو Public
Derivative تحفظ منفصلة.” (SPEC-U11-009/U11-011; D-031). The additional behavior is
a durable private technical thumbnail/playback workflow, with real local ffmpeg
execution and separately stored outputs. A job identifies one exact attachment,
answer part or library version by protected foreign key. An output identifies
that job, source digest, attempt, current lease, recipe version, actual engine
and probe identity, output type/size/hash. Its bytes are in `DerivedOutput`, never
in any original source, answer, evidence, transcript, citation, decision,
publication or delivery row.

Existing public media editions and manually revised/reviewed transcripts remain
independent workflows. Tests preserve actual nonempty transcript/action and
public-edition/action histories while optional processing fails and retries.
Owner 441 is explicitly excluded from new credit: the same separation and
original-byte assertions already exist at anchor `ac8f517`, as documented in
README. Owner 432 remains partial: there is no actual ASR provider. A disabled
technical decoder is not evidence for transcription-service continuity.

## Authorization and exact originals

`sources.read` first resolves the exact source inside the current authorized
case. Existing attachment/answer/library readers remain responsible for the
original bytes, current parent/child classification and current clean scan. The
derivative does not authorize that original. A second independent derivative
permission admits CREATE, EXECUTE, READ, DOWNLOAD, RETRY or CANCEL. DOWNLOAD also
requires READ, classification EXPORT and the existing source export permission
(Library DOWNLOAD or case-media EXPORT_MEDIA).

The view only returns authorized rows; skipped sources/jobs do not enter result
counts or choices. Source owner/version/decision state, canonical case state,
identity claims and pure provider/policy revisions are pinned. Every callback
finishes before final pure source/privacy/scan checks. The same pure checks are
retained after the final real Session USE callback, including for signed
GET/HEAD/Range. A ticket binds source and browser state but grants no right.
Expiry is separate from policy version: the new explicit per-permission
`grant_deadline` is timezone-aware, current and at most one hour ahead; every
scope retains the minimum. It never substitutes an actor deadline for a missing
grant or extends READ using a later DOWNLOAD grant. The RED regression exposed
that exact previously missing condition at the final HTTP session boundary.

The worker resolves the actual configured current directory and exact stored
submitter. It requires an independent current EXECUTE grant; no machine
principal, browser cookie, request lease or role privilege is invented. A saved
origin Session and exact MFA SessionAssurance/Factor are additional vetoes.
Current session/MFA permissions, revocation and expiry are checked before claim,
after processing and after final callbacks. Saved factor history cannot be
ignored by disabling/removing MFA. Native reads of completed work still require
the new caller's current authorized session; an old completion grants nothing.

## Processor and data leaving the domain layer

There is no remote AI provider, HTTP client, model key, prompt, transcription
dispatcher or publication call in this app. The only processor is the exact
server-configured `FFmpegProcessor`. Browser input is a finite task and exact
source UUID; it cannot select an executable, file path, URL, codec option or
filter. CLI execution similarly selects a saved job or a finite current batch,
not a subject identity or arbitrary command.

The child receives original media bytes, declared MIME, the finite task and the
two explicitly configured local binary paths. It receives no staff identity,
session cookie, API key, case question, answer/transcript text or authorization
object. Its environment is the explicit PATH/locale/PYTHONDONTWRITEBYTECODE set,
not inherited application secrets. The media worker imports no Django models or
database connection. Input/output go through pipes and the ffmpeg/ffprobe
protocol whitelist is `pipe`; external playlists and arbitrary filters are
rejected. Executables must be configured absolute regular executable files,
not group/world writable; file digests/stat and actual version output are
checked before and after work. Only fixed failure codes and bounded version
provenance are persisted, never subprocess stderr or arbitrary provider errors.

The parent limits the child process group by wall time and pipe output, cancels
and reaps on failure, and has one process slot. The worker applies CPU, memory,
file-size and descriptor limits; each decoder call has its own timeout. A
separate database lease limits current execution across processes. CPU decoding
occurs between two short authorization transactions, never while the canonical
case/source transaction is held. These controls are not a container/security
namespace proof and do not imply production decoder hardening.

## Content and durable state

THUMBNAIL scales the complete first frame to a bounded PNG with preserved display
aspect, including non-square video pixels. It does not crop or choose a
user-supplied timestamp. AUDIO_PLAYBACK retains the complete admitted audio
track, sample rate and channel count; it does not trim, denoise, synthesize,
resample or silently truncate at an output cap. A video must contain exactly one
video track and at most one supported audio track. Audio output beyond the
bound is rejected. The PCM output is compared with source duration; uncompressed
WAV also preserves exact frame count. These are technical derivatives, not
scientifically reviewed edited public material.

SQL independently enforces immutable sealed records, exact source ownership and
hash/size, bounded history, ordered predecessor digests, current attempt/lease,
matching output and complete/fail transitions. Idempotent request and stale
sequence checks prevent duplicate actions. Explicit retry is bounded to four
attempts; cancelled/stale workers cannot commit a late result. A recorded
FAILED/UNAVAILABLE result leaves the source untouched. Revocation can leave a
RUNNING claim to expire; the UI distinguishes that from successful completion.
No silent retry or success is manufactured.

SQL integrity is not an authorization grant. Authorization remains at the
service/source/session boundaries. Likewise, a clean source receipt does not
make a file public or authorize child access. Generated output is not a new
upload admission: the fixed PNG/PCM recipe is validated, sealed, and its exact
original must still have a current clean receipt on every use.

## Recovery and verification limits

The helper populates three nonempty derivative tables with actual ffmpeg READY,
UNAVAILABLE and CANCELLED histories. It fingerprints all table rows (including
output bytes) and original case/evidence/event/attachment rows. Restored reads
use newly supplied current trust, preserve exact hashes/provenance and do not
execute a decoder or scanner. Fourteen explicit denial cases are followed by a
positive read and an unchanged-ledger check. The scanner fixture is explicitly
synthetic; actual ClamAV evidence belongs to its independent engine acceptance.

The original eight-class group and later MFA group passed together as 46 tests
on PostgreSQL 17 and 18 at `b3c33145d6c98c3e6144bcd5e5971d392c382c40`. The two
grant-expiry regressions were demonstrated RED before their fix and require the
following head's green run. Protected local Chromium was blocked before
navigation by an OS socket restriction; this is not browser acceptance. Exact
hosted browser and fresh-target encrypted aggregate restore evidence remain
coordinator-owned requirements for nominating owner 382.

The implemented envelope remains development-only and closed by default: input
at most 192000 bytes, output at most 8 MiB, one current worker lease, at most 64
jobs per case, 24 events per job, four attempts and a ten-minute execution
window. Larger-media ingestion, production object storage/worker topology,
ASR provider/quality and semantic public redaction are outside this evidence.
No main merge or production activation is implied.
