# Pause and resume one original recording

The existing native recorder now supports **إيقاف مؤقت** and **استكمال التسجيل**
within the same recording. Previously, stopping completed the capture and a new
start discarded its samples. Pausing now retains the captured samples, disables
audio tracks after the worklet acknowledges the pause, and adds no paused-time
samples. Resume continues the same buffer and microphone session. Stop from
either recording or paused state creates one local WAV for listening and explicit
selection into the original upload form.

The existing bound remains 80,000 mono PCM16 samples at8kHz: ten seconds of
captured audio, up to160,044 WAV bytes. Pauses do not reset this budget and do not
insert silence. The elapsed-time and byte counters derive from the retained
sample count. A paused session expires after60 seconds and cancels completely;
the UI discloses this bound. A pause or resume that receives no worklet
acknowledgement within one second fails closed. The recording watchdog uses the
remaining sample budget rather than the total wall time including pauses.

The worklet and main thread use the same ordered message port. Acknowledgement
therefore follows all previously captured PCM; an in-flight final block cannot
silently disappear when entering the paused state. Resume acknowledges before
new PCM is consumed. A budget-ending block during the pause transition still
finishes the recording correctly.

Cancel, form reset, page departure, hidden page, microphone loss, context
interruption and worklet failure release the existing tracks, context, port and
preview URL. Native form submission is blocked while permission, capture, pause,
resume or unaccepted preview is pending. No recording is uploaded automatically,
and no extra file field, permission grant, endpoint or server limit is introduced.

## Evidence and limits

- `node --test apps/browser_audio/test_capture_worklet.mjs` exercises real
  worklet processing with explicit PCM input: exact samples across a pause gap,
  unchanged budget across repeated pauses and invalid input/control rejection.
- `apps.browser_audio.test_browser.BrowserAudioTests.test_pause_resume_preserves_one_recording_and_excludes_paused_time`
  runs the real Chromium audio/worklet chain with a generated synthetic microphone
  file. It verifies stable frames while paused, disabled tracks, one microphone
  session, continued samples, blocked premature native submission, a single WAV,
  and exact server-validated retained bytes/hash after upload.
- The integrated completion workflow requires `FATWA_BROWSER_SANDBOX=1` and runs
  this browser scenario on PostgreSQL17 and18. Service or Node success alone is
  not a protected-browser pass. The local workstation's protected Chromium launch
  was denied before page startup; no sandbox bypass was used for this change.

This implements the missing pause/resume part of owner point77 / SPEC-U02-013.
The original recording and approval rules remain as documented in CONTRACT.md.
The ten-second synthetic development bound is explicit; no unlimited recording,
universal device compatibility, production readiness or new percentage claim is
implied. Historical V14 evidence remains historical.

**NOT_DEPLOYED. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED.**
