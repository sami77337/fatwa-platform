# V14 recording: progress, interruption and maintenance

Base: PR #232, `1f08cbb7166f70ec340c495da33ccfc1eda9534e`, verified against
remote `codex/20261118-v13-integration` before creating
`codex/20261118-v14-recording`. V13 history is preserved. Owned changes are entirely
inside `apps/browser_audio/**`.

## Behavior and unchanged limits

The same explicit permission/start button now leads to visible elapsed sample
duration, WAV byte size and a progress bar during capture. Metrics update at most
four times per second and are not an ARIA live region; discrete start/error/preview
announcements retain the existing polite status region. Final metrics use the exact
retained frame count and remain visible after accepting the file into the native
upload control. Cancel, reset, replacement and error clear the metrics with the
recording. 320-pixel RTL is exercised in real Chromium.

The bound stays **10 seconds, mono 8000 Hz PCM16 WAV, 160044 bytes**. It is stated
in the component alongside the counters. The unchanged server cap is 192000 bytes;
there is no silent MIME, duration, size or quality expansion. Duration comes from
captured samples, not wall-clock permission wait; live size is the WAV header plus
captured samples (zero before any samples). These are local estimates until the
existing isolated server parser validates the actual submitted file.

AudioContext suspension/interruption now cancels recording and closes the
microphone instead of permitting a truncated capture to appear complete. The
11-second wall-clock watchdog now fails a stalled capture instead of constructing
a partial preview. Normal frame-limit completion still produces the exact 10-second
WAV and explicitly reports that the limit stopped the microphone. Manual stop
continues to permit a shorter preview. Cancellation, pending/late permission, device
loss and worklet failure retain their existing cleanup. Tests now observe actual
worklet port closure/disconnection in addition to native ended tracks, closed
contexts and revoked preview URLs. Replacing an accepted capture with a separately
selected file preserves that file and drops the stale preview.

## Shared-template contract for the integrator

V13 already wires the owned include into initial question intake, requester
attachment/reply and Mufti answer forms. Preserve those includes, their existing
native file names, CSRF/proof/revision/synthetic-confirmation fields, scoped CSP,
permissions policy and opt-in. The new metrics live **inside the owned include**;
there is no new route, request field, flag, authority, model or migration to wire.
Update the template, CSS and JS together. No shared security-policy change is needed.

Keep each include inside its native multipart **form**, but outside the file
control's `<label>`. The legacy `case_attachments/desk.html` include at this base
is still nested in that label; correcting its placement belongs to integration.
Do not duplicate the include in a form or copy its counters into shared templates.

The canonical type/hash/version/duration contract from [CONTRACT.md](CONTRACT.md)
remains unchanged. Temporal citations must continue using server-validated original
bytes and immutable identities, never the local counter or blob URL. No ASR,
transcription, external service, scanner claim or new role is introduced.

## Maintenance and privacy boundary

The recorder does not poll a new maintenance endpoint or upload automatically.
An already loaded page can hold a local preview; the existing outer MaintenanceGuard
is authoritative for every HTTP write and worklet asset fetch. A freeze after local
acceptance refuses the original form POST with 503 and writes no file/evidence.
The rejected native navigation discards the preview. Resumption requires explicit
operator action through the existing maintenance contract and a new user recording
and save; there is no automatic retry or background upload.

The new test uses `config.campaign_urls`, native V13 templates/CSP/asset routes and
the actual outer maintenance middleware, with the old HTML-injection test shim
absent. It proves frozen save/asset refusal, no attachment/blob or Evidence change,
explicit generation-bound resume, exact original bytes after a new recording, and
private sandbox/no-store byte headers plus outsider denial. It does not claim a
server freeze can remotely stop an already-running browser microphone without a
separate approved client coordination protocol.

## Focused verification

Run the affected browser module using the existing fresh synthetic cluster runner:

```sh
python -m infra.dev.with_casework_postgres --pg-bin /path/to/postgresql/17/bin --major 17 --settings config.settings.campaign_review -- python manage.py test apps.browser_audio.test_browser --noinput --verbosity 2
```

Repeat using PG18 binaries and `--major 18`. Dependencies and synthetic microphone
flags remain those recorded in V13. All input is a generated temporary sine WAV,
with native Chromium getUserMedia/AudioContext/AudioWorklet; no real microphone or
voice. The five scenarios are the three affected V13 browser journeys plus live
metrics/interruption/reset and the strict native maintenance journey. Unchanged
server-boundary and unrelated app suites are not rerun locally.

Local evidence and initial harness failure are in [V14_EVIDENCE.md](V14_EVIDENCE.md).
Protected-Chrome integration CI remains required; local runs explicitly use
`FATWA_BROWSER_SANDBOX=0` under the previously documented environment limitation.
No system sandbox, shared rights check or repository/GitHub setting was changed.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No production pilot,
acceptance, percentage estimate, universal device support or independent security
review is inferred from these implementation tests.
