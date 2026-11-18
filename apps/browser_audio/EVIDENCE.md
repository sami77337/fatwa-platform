# V13 audio capture — executed evidence

Date: 2026-11-18. Base PR #231 SHA
`5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`, confirmed with `git ls-remote` on
`codex/20261117-v12-integration`; new branch `codex/20261118-v13-audio-capture`.
Only `apps/browser_audio/**` changed. Shared files and V12 branches preserved.

## Focused results

| Executed check | Result |
| --- | --- |
| PG17.12: initial two browser journeys and four boundary tests | 6/6 PASS, 18.312 s |
| PG17.12: added worklet/cancel/device failure browser test | 1/1 PASS, 2.775 s |
| PG18.7: all seven owned tests | 7/7 PASS, 20.229 s |
| Django system checks (both temporary clusters) | PASS |
| Scoped Ruff check and format check | PASS |
| `git diff --check` | PASS |

Each database run used `infra.dev.with_casework_postgres` to create and destroy
a new owned synthetic cluster with real migrations. Python 3.13.5, Playwright
1.62.0, Chromium 154.0.8037.57. Local browser runs explicitly used
`FATWA_BROWSER_SANDBOX=0`. **Protected-Chrome verification is pending integration**;
these results do not imply sandboxed Chrome or final combined V13 CI success.

Test coverage, with actual original views/services/private filesystem:

- Browser-generated nonzero PCM WAV passes the existing isolated byte validator.
  A microphone fixture is synthesized in a temporary file, never a real device.
  The 10-second automatic stop produces exactly 160044 bytes, mono, 8000 Hz,
  16-bit samples and server-validated duration 10 seconds. Mobile-width RTL does
  not overflow at 320 pixels.
- Native requester form saves the exact hash/bytes to external private storage
  (`original IS NULL`), increments Evidence 1→2 and invalidates the old approval.
- Native scoped Mufti multipart form retains old parts and saves the recorded WAV
  in a new answer revision, leaving Evidence at 2. Explicit human fixture approval
  and separate release make it privately readable. A later browser recording
  invalidates approval and closes the old private read, while its original bytes
  remain intact. Anonymous attachment reads and ORGANIZER answer reads are refused.
- Page initialization makes zero microphone requests. Actual browser permission
  denial (CDP permission on the correct browser context) releases the AudioContext.
  A native synthetic stream whose permission promise is held until after cancel
  is stopped upon late resolution. Cancel after acceptance clears only the capture
  file and revokes the URL. Pagehide releases all tracks/contexts.
- Real worklet asset refusal stops the acquired microphone. Device-ended event
  handling and cancel while recording release tracks/contexts, create no database
  row and preserve an independently selected file. Native submit is prevented
  while recording, even when the original form is otherwise valid.
- Malformed WAV, forged WebM MIME, missing synthetic confirmation, missing CSRF,
  wrong upload proof and stale revision are refused by the existing server paths.
  Production mode/absent opt-in disables the new presentation/assets; filenames,
  methods and query handling of fixed assets are bounded.
- Page request interception rejects nonlocal destinations; successful tests
  recorded no such page requests. No external service, ASR or real send was used.

## Initial failures retained

The first browser launch with sandbox enabled aborted because the environment's
Chromium sandbox helper was not configured correctly. No system security setting
was changed. A writable temporary XDG configuration path was provided for later
local launches, with the explicit local sandbox limitation above.

Early harness attempts failed because the observation init script was declared
without invocation, and Playwright string predicates attempted CSP-forbidden eval.
The harness now invokes its script and uses function predicates; the CSP was not
weakened. The default fake audio device supplied initial silence, so a generated
440-Hz WAV now supplies nonzero samples. Permission override originally targeted
the wrong browser context; the corrected test uses that context's actual ID and
grants/denies native microphone permission without the fake-UI bypass flag.

The added worklet-failure test initially used a page-route interception that did
not intercept the worklet load. It now temporarily closes the actual asset flag,
observes real HTTP refusal and checks cleanup. That affected test passed on PG17,
then all seven passed on PG18. No unsuccessful attempt is counted as a pass.

Successful local logs: `/tmp/v13-audio-pg17-fifth.log`,
`/tmp/v13-audio-pg17-failures-second.log`, `/tmp/v13-audio-pg18.log`.
These are local execution logs, not uploaded CI artifacts or an independent
security review. No audio fixture, key, browser profile or database was committed.

## Handoff limits

See [CONTRACT.md](CONTRACT.md) for template include, exact asset routes, opt-in,
scoped CSP/Permissions-Policy and immutable audio/citation identity contract.
The tests compose these changes within the owned test harness; the integrator
still owns actual shared template/guard/config/CI edits and their verification.
No Firefox/Safari/real hardware, malware scanning, independent security acceptance,
production pilot, new completion percentage or gate advancement is claimed.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
