# V14 recording execution evidence

2026-11-18, branch `codex/20261118-v14-recording`, base
`1f08cbb7166f70ec340c495da33ccfc1eda9534e` (remote V13 integration/#232 verified).
Only owned browser-audio paths changed; no shared configuration, rights checks,
media allowlist, GitHub settings or V13 branch was changed.

| Execution | Observed result |
| --- | --- |
| PG17.12 initial affected browser module | Four PASS; maintenance fixture ERROR, 53.361 s |
| PG17.12 corrected native maintenance test only | 1/1 PASS, 3.837 s |
| PG18.7 final affected browser module | 5/5 PASS, 25.693 s |
| Django system checks in both temporary clusters | PASS |
| Scoped Ruff lint/format and whitespace checks | PASS |

The initial maintenance test tried to replace middleware inside a live server that
had already built its middleware chain. The required admission guard therefore
refused the first page, and the browser timed out looking for the unlock field.
The corrected maintenance test has its own LiveServerTestCase with the real native
middleware/URL configuration applied **before server creation**. Required maintenance
admission remains enabled for the test requests; assertions were not weakened.
Only that affected test was repeated on PG17, then the five affected browser
scenarios ran on PG18. No unrelated successful app suite was rerun.

The four original passing PG17 scenarios cover native private requester/answer
uploads, approval invalidation, permission denial/late-grant cancellation/10-second
limit, worklet failure/device loss, and the new live counters/AudioContext suspension/
file replacement/form reset. The fifth corrected scenario uses the integrated
native template, CSP, routes and real maintenance guard: FROZEN rejects upload and
worklet fetch with 503, leaves zero attachment rows/blobs and unchanged Evidence;
explicit generation-bound resume permits a fresh capture and native upload with
exact byte/hash preservation and private sandbox/no-store headers. An outsider
cannot fetch those bytes.

New counter assertions compare live displayed bytes/duration/progress with each
other, and final metrics with the actual parsed WAV. Native engine suspension
causes error/cancellation, zero metrics and no selected recording. Worklet ports
are observed closed and nodes disconnected; real tracks end and contexts close.
Cancel/replacement/reset revoke URLs without replacing the user's independently
chosen file. A 320-pixel RTL page stays within the viewport. All test audio is a
generated temporary 440-Hz sine WAV through Chromium fake-device/file input, not
a mock replacement for the native recording engine or a real microphone.

Local logs: `/tmp/v14-recording-pg17.log`,
`/tmp/v14-recording-pg17-maintenance.log`, `/tmp/v14-recording-pg18.log`.
Python 3.13.5, Playwright 1.62.0, Chromium 154.0.8037.57, fresh owned synthetic
PostgreSQL clusters via the repository runner. Temporary synthetic private roots
and microphone files are cleaned up. No audio bytes, identities or keys are saved
as repository artifacts.

These local browser runs explicitly used `FATWA_BROWSER_SANDBOX=0`, preserving
the V13 environment limitation. They are not protected-Chrome or hosted-CI proof.
Protected-Chrome testing on the final integrated head remains the integrator's
responsibility. The old sandbox failure was not retried or represented as a V14
pass. No security configuration was changed to make it run.

The wall-clock stall watchdog's new fail-closed branch is source-reviewed; native
AudioContext interruption and normal frame-limit completion are executed. This
does not claim a separate elapsed-11-second renderer-starvation simulation.
No real hardware/Safari/Firefox support, independent security acceptance,
production pilot, ASR, external service or scanning claim is inferred.

Shared-template and unchanged temporal/media contracts: [V14_RECORDING.md](V14_RECORDING.md).
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No new estimate.
