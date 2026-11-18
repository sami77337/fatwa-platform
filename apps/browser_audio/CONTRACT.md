# V13 browser audio — integration contract

V14 additions and current shared-template handoff: [V14_RECORDING.md](V14_RECORDING.md).
The original media type, storage and canonical identity contract below is unchanged.

Base: PR #231, `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`, verified against
`origin/codex/20261117-v12-integration`. Ownership: this new app only. No database
models, upload endpoint, permission provider, media allowlist or shared settings
were replaced. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.

## Integrator changes required

1. Register `apps.browser_audio` for its template. Add context processor
   `apps.browser_audio.context.capture`. Keep `FATWA_BROWSER_AUDIO_ENABLED=False`
   by default; enable only in the explicitly synthetic local review profile.
   The context and fixed asset views also require the existing casework flag and
   `FATWA_PRODUCTION=0`.
2. Include `browser_audio/capture.html` **inside the existing multipart form**:

   ```django
   {% include "browser_audio/capture.html" with audio_input_name="attachment" %}
   ```

   Use `audio_input_name="answer_file"` for the multipart answer editor.
   The requester portal and legacy attachment desk use `attachment`. The current
   clarification reply uses `reply_attachment` and the same component supports it;
   its atomic reply path still requires its existing text/proof fields. The focused
   tests cover attachment and answer forms, not the optional reply composition.
   Include at most once per form. It matches the native file input within that
   form, adds no submitted fields, and never sends a request itself.
3. Add `apps.browser_audio.assets.urlpatterns` to the shared URL composition and
   `assets.ASSET_ROUTES` to the existing guard's exact GET/HEAD route map. These are
   `/casework/audio-capture.js`, `/casework/audio-worklet.js`, and
   `/casework/audio-capture.css`. Preserve loopback, query/method/body limits,
   maintenance admission and rate budgets. Assets are fixed filenames with
   no-store/nosniff responses; there is no user-supplied filesystem path.
4. On **the private HTML responses containing this component only**, append
   `script-src 'self'; worker-src 'self'` to the existing CSP and extend
   `media-src 'self'` to `media-src 'self' blob:` for local audio preview. Preserve
   `default-src 'none'`, existing form/frame/base restrictions and other headers.
   Set `Permissions-Policy: microphone=(self), camera=()`. Do not add unsafe-inline,
   unsafe-eval, remote script origins or a cross-origin microphone permission.
   Existing private byte responses must retain their sandbox CSP unchanged.

`test_support.py` is **test-only composition**, not an installable middleware:
it inserts the real include in the existing server-rendered form and applies those
specific headers, leaving the original views, CSRF, scope and storage code intact.
Do not use that HTML rewriting middleware in the integrated application. Shared
templates, dispatch/config/guard and CI remain owned by the integrator.

## Capture and upload behavior

The initial page does not request permission or enumerate devices. The explicit
Arabic button requests microphone permission and starts recording after grant.
Stop yields a local preview; a second explicit button accepts the file into the
native input. The original form's synthetic confirmation and save are still
required. No automatic save, ASR, transcript, external service, delivery or approval
is added. A native file input remains usable when capture is unavailable.

Capture uses standard Web Audio: `AudioContext({sampleRate: 8000})`, mono
`AudioWorklet` samples, PCM signed 16-bit WAV encoding. The context's actual rate
must be exactly 8000; unsupported engines fail closed, without relabeling WebM or
pretending a successful transcode. The graph outputs silence to prevent microphone
feedback. Maximum 80000 frames = 10 seconds = **160044 bytes**, below the unchanged
192000-byte private-media limit. A wall-clock fallback stops a stalled renderer.
The limit is intentionally short for this prototype; increasing quality/duration
requires a separately validated storage/media contract.

Cancel stops every track, closes the AudioContext/port, discards sample buffers,
revokes the preview URL and clears only the file assigned by this component.
An independently chosen file is preserved. Late permission resolution after cancel
immediately stops the returned stream. Failure, device-ended events, form reset,
pagehide and hiding the page while capturing also release resources. A pending
capture or unaccepted preview prevents ordinary form submission. The server is
still authoritative if a forged client bypasses those UI affordances.

The original browser-generated WAV becomes the upload original. It is never
normalized server-side by this component. Existing isolated parsing validates
actual bytes, size, type and duration before private storage; that is structural
validation, **not malware scanning**. Existing services link the upload to canonical
case/evidence or immutable answer revision, enforce permissions and optimistic
revision/proof checks, and revoke prior approval/private availability as appropriate.
Requester audio changes Evidence; answer audio creates an answer revision without
inventing new Evidence. No extra role, capability or approval is created here.

## Contract for temporal citations

| Field | Authoritative source |
| --- | --- |
| `filename`, `media_type`, `size`, `sha256` | Existing persisted attachment or answer part |
| Captured type | `capture.wav`, `audio/wav`, PCM16LE, mono, 8000 Hz |
| `duration_seconds`, `sample_rate`, `channels` | Existing isolated server parser metadata |
| Case recording identity | `CaseAttachment.id`, case, associated Evidence version |
| Answer recording identity | `AnswerPart.id` → manifest → immutable AnswerRevision + Evidence version |
| Permission/read URL | Existing authenticated attachment/answer byte service, rechecked per request |

Attachment metadata is `validation_metadata`; answer part metadata is `metadata`.
Do not persist a `blob:` preview URL, trust UI duration, infer a transcript, invent
timestamps, or point citations at an unaccepted local recording. Zero is the first
sample of the retained WAV; any future span must be bounded by its validated
duration and pinned to the exact original hash and canonical immutable identity.
Browser/device processing and browser resampling precede WAV creation: no claim
of lossless archival of the microphone's physical signal or an unavailable source
format. Preservation applies to the exact accepted WAV bytes.

## Checks and boundaries

Run only the owned tests with the existing synthetic PostgreSQL runner:

```sh
python -m infra.dev.with_casework_postgres --pg-bin /path/to/postgresql/17/bin --major 17 --settings config.settings.campaign_review -- python manage.py test apps.browser_audio.test_browser apps.browser_audio.test_boundaries --noinput --verbosity 2
```

Repeat with PG18 binaries/`--major 18`. Browser test dependencies match existing CI:
Playwright 1.62.0, pyee 13.0.1, greenlet 3.5.5, Chromium executable selected through
`FATWA_FASTBUILD_BROWSER` (default `/usr/bin/chromium`). Tests default to sandboxed
Chrome; `FATWA_BROWSER_SANDBOX=0` is an explicit local limitation, not CI proof.
The only microphone input is a generated temporary 440-Hz sine WAV through Chromium
fake-device/file flags. Page network requests outside the loopback server are blocked.

Actual results and initial failures: [EVIDENCE.md](EVIDENCE.md). Firefox, Safari,
mobile hardware, real voices, production/public deployment and independent security
acceptance are not claimed. The integrator must verify its real template/CSP/guard
wiring and protected-Chrome run; this branch intentionally does not edit them.

API references: [AudioContext sampleRate](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/AudioContext),
[AudioWorklet sampleRate](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletGlobalScope/sampleRate).
