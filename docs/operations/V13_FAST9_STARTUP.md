# V13 FAST9 startup evidence — ROOT_CAUSE_UNKNOWN

Read-only investigation on 2026-11-18. No workflow rerun, product test execution,
timeout/flag/sandbox change, or browser-runner replacement was performed. This
document does not mark the failed browser gate passed or diagnose a flake.

## Precisely identified boundary

[Failed run 44218120292](https://github.com/sami77337/fatwa-platform/actions/runs/44218120292),
[job 134512970271](https://github.com/sami77337/fatwa-platform/actions/runs/44218120292/job/134512970271),
attempt 1, workflow `FAST9 integrated local development journey` number 127:

- Run head: `0c8d653f86c3cd425a1e0e12c0e850aac5732128`.
- Actual checkout/receipt: merge `5a5526f4ad929b71e21faefa083c8f7316f46733`,
  merging that head into `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`.
- Services: 114 tests PASS; HTTP: 31 tests PASS.
- At `2026-11-18T01:45:19.9787720Z`, the harness emitted `FAIL`,
  `stage=browser_startup`, `TimeoutError`, `category=playwright_timeout`,
  `harness_line=352`. The shell then exited 1.
- At this exact source revision, line 352 is `driver.chromium.launch(...)`,
  with `executable_path=executable`, `chromium_sandbox=True`, and
  `timeout=TIMEOUT`; `TIMEOUT = 10_000`. The path is required to be the existing
  `/usr/bin/google-chrome`. `sync_playwright()` context entry at line 351
  returned before this call. No Browser object was returned to the harness.
- `browser=null`, `views=[]`, `login_observations=[]`: version lookup and all
  page/context/role journey work after the launch call were not reached.
  Zero page errors and unexpected requests are untouched initial counters, not
  evidence of successful page checks. `journal_unchanged=false` is also an
  initial value: the final comparison was not reached, so it proves neither
  mutation nor successful preservation.

The configured **launch** timeout is 10 seconds. The log does not measure exact
launch elapsed time or its internal subprocess/transport phases. Time between
pip completion and the failure also contains Python/driver setup and fixture/server
work; it must not be reported as an isolated launch or WebSocket duration.

## Previous successful execution of the same workflow

[Run 44216988078](https://github.com/sami77337/fatwa-platform/actions/runs/44216988078),
[job 134509183037](https://github.com/sami77337/fatwa-platform/actions/runs/44216988078/job/134509183037),
attempt 1, workflow number 126:

- Run head `908b17b046d58abbee833b511355e38e1592cf32`; actual receipt/checkout
  merge `79109da373c4fa820296d53d1614afb4b1b2452e` against the same V12 base.
- 114 service tests and 31 HTTP tests PASS. At `01:36:29.5364729Z`, browser
  evidence reported `PASS`, `stage=complete`, Chrome `157.0.8103.50`, four
  author/reviewer views at 320px/1280px, three successful role logins, zero
  unexpected requests/page errors, and `journal_unchanged=true`.
- Both logs report runner `2.338.2`, Ubuntu `26.04.1`, image
  `ubuntu-26.04` version `20261111.196.1`, provisioner `20261103.629`,
  CPython `3.13.18`, Playwright `1.62.0`, pyee `13.0.1`, greenlet `3.5.5`.
  The successful worker was in `eastus2`; the failed worker was in
  `northcentralus`. Different workers/regions do not establish a cause.
  The failing Chrome binary version was not independently logged, so equality
  of the image label does not prove equality of the actual browser binary.

Local Git comparison confirms byte-identical files at the two run **heads**:

| File | SHA-256 at both heads |
| --- | --- |
| `tests/editorial_workbench/return_preparation_browser.py` | `9b55209999dabcc1a4780ad0965a00dd11aaeec7605452419908c53b881c9987` |
| `.github/workflows/fast9-integrated-journey.yml` | `128a526a113387170f243c392f96ee0f604a0cd72e03b9fb09588656ff4c3833` |
| `requirements.txt` | `8c7f2e99030e4a95706fc0b6a4872d308fa3be95fd329524cc03a61838d54e9b` |

Other campaign files did change. Equal harness bytes and a prior pass are not
proof that application changes or environment factors are irrelevant. This
comparison uses two different heads; it is not a same-head retry experiment.

## What remains unknown; bounded next diagnostic change

The logs contain no browser subprocess lifecycle, launch-phase elapsed times,
sanitized launch call-log classification, browser exit state, resource-pressure
measurement, or failed binary version. The harness intentionally does not output
raw Playwright exceptions, since they can contain private inputs/HTML. No observed
evidence distinguishes a process-launch stall, connection/setup stall, resource
issue, or another launch failure. Browser cleanup is not separately instrumented;
the `browser.close` callback is registered only after launch returns, while the
Playwright context manager still owns its exit behavior. Do not infer a cleanup
failure or success from the absence of its metric.

Recommendation only, not implemented here: retain the existing Playwright runner
and 10,000ms launch timeout; add a small fixed startup record using monotonic
timings around driver entry and the launch call, plus fixed entry/return/failure
states and configured sandbox/timeout values. Record a version via a separately
bounded local version probe if needed, explicitly labeling it a preflight probe
rather than successful launch. Any further Playwright call-log analysis must
emit only reviewed fixed classifications and never raw stderr, exception text,
URLs, command lines, environment values, profile paths, tokens, or arbitrary
arrays. Do not infer undocumented internal process states or disable sandboxing
to obtain a pass. New diagnostics need their own focused privacy/failure tests.

The V13 `ProtectedBrowser.startupDiagnostics` instrumentation applies to the
Node protected harness/research wrapper; this FAST9 Python Playwright launch
does not call it. Historical D6's 30,001ms total-startup observation therefore
does not explain this failure. Both incidents retain their separate unknown-cause
status until evidence supports a causal conclusion.

Evidence source: directly fetched decoded GitHub job logs and workflow-run/job
metadata plus the pinned repository source. These fingerprints cover the exact
tool-returned decoded log string re-encoded as UTF-8, including its leading BOM;
they are not hashes of a downloaded ZIP or unexamined transport bytes:

| Job | UTF-8 bytes | SHA-256 of decoded log |
| --- | ---: | --- |
| Passing `134509183037` | 71124 | `54b41676b0e6087d1620dfacabb20afb0f0947f05c23e31b53ed02c5d2195ab2` |
| Failed `134512970271` | 68440 | `994042574c26f50943188ced17e9e2d19b3672fc52ff150ecf23568e23137186` |

Artifacts were logged as uploaded
(failed artifact `14389477022`, 682 bytes; passing `14387763962`, 969 bytes), but
their ZIP bytes were not downloaded or inspected in this bounded investigation.
No GitHub configuration or production action occurred. Gate B `NOT_PASSED`,
C/D/E `HOLD`, Phase01 `BLOCKED`, `NOT_DEPLOYED` remain unchanged.

## Subsequent natural runs: another launch timeout, no established cause

The following evidence was fetched separately on 2026-11-18. Both runs were
attempt 1; this investigation neither requested nor executed a rerun.

| Observation | Previous PASS | New FAIL |
| --- | --- | --- |
| Run / workflow number | [44221424455 / 129](https://github.com/sami77337/fatwa-platform/actions/runs/44221424455) | [44222225041 / 130](https://github.com/sami77337/fatwa-platform/actions/runs/44222225041) |
| Job | [134523955880](https://github.com/sami77337/fatwa-platform/actions/runs/44221424455/job/134523955880) | [134526634674](https://github.com/sami77337/fatwa-platform/actions/runs/44222225041/job/134526634674) |
| Run head | `09cc55aa021660f593bb1b70e850d0f448ddad3a` | `cd22cbd265db4b57124a1f091a041fd5200637b8` |
| Tested merge checkout/receipt | `00692f27bd0c455edb7a3ce63bb2e47d9482da2a` | `a3753f89039ce51e4ddd6485e12ee2bd406862e2` |
| Merge base | `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8` | same |
| Service / HTTP tests | 114 / 31 PASS | 114 / 31 PASS |
| Runner image | `ubuntu-26.04`, `20261111.196.1` | `ubuntu-26.04`, `20261111.82.6` |
| Hosted cloud / region | Azure / `westcentralus` | AWS / `us-east-1` |
| Browser receipt time, UTC | `02:12:21.7538533` | `02:18:47.6807031` |

Both logs report runner `2.338.2`, provisioner `20261103.629`, Ubuntu `26.04.1`,
CPython `3.13.18`, Playwright `1.62.0`, pyee `13.0.1`, and greenlet `3.5.5`.
The passing receipt identifies Chrome `157.0.8103.50`, four author/reviewer
320px/1280px views, three successful role logins, no unexpected requests/page
errors and `journal_unchanged=true`. The failing receipt again records
`browser_startup`, `TimeoutError`, `playwright_timeout`, harness line **352**,
`browser=null`, empty views/logins, zero initial counters and
`journal_unchanged=false`. The latter is still an unchecked post-journey invariant,
not proof that a journal changed. No actual failing browser version or process
exit/stderr/phase evidence is recorded.

The FAST9 harness, workflow and requirements are byte-identical between these
two heads, with the same three SHA-256 values already listed above. The only
changed paths between the heads are three documentation files and the separate
Node diagnostics test. That Node test is not invoked by FAST9. This rules out a
change to the inspected FAST9 launch call, its **10,000ms** limit, or that test's
runtime settings as a code delta between these two executions. It does not
establish why the unchanged launch call timed out. The different cloud, image
revision and region are observed differences, not controlled causal evidence.

The repeated failure has the same **observable symptom and boundary** as run
44218120292. It is not evidence that the hidden cause is identical, a proven
flake, or the same cause as historical D6. Status remains **ROOT_CAUSE_UNKNOWN**.
Passing intervening runs preserve their own evidence without erasing either
failure. A later normal run, whether pass or fail, will not retroactively supply
the missing launch diagnostics.

Additional exact decoded-log UTF-8 fingerprints (including leading BOM, not ZIP):

| Job | UTF-8 bytes | SHA-256 |
| --- | ---: | --- |
| Passing `134523955880` | 70537 | `b1a7973f672a64bed5b8eeabd583fa357bbc606461d0c339c485e8a5eff5c7b8` |
| Failed `134526634674` | 68429 | `34e12d0861ff45f612cc5dd7315712d7cfeaca787fb9750dfaa8b38733090766` |

The logs record uploaded artifacts `14390073303` (passing, 971 bytes) and
`14391381325` (failing, 681 bytes). Their ZIP bytes were not inspected here.
No product tests or browser runs were repeated for this document update.

A further **unimplemented** proposal was sent to integration: measure monotonic
driver-entry/launch durations around the existing calls; on launch errors only,
scan a bounded in-memory message for reviewed fixed call-log milestone and
exit/known-stderr categories. Export no raw message, stack, URL, path, PID or
stderr. Keep missing markers `NOT_OBSERVED`; a logged exit may be timeout cleanup
rather than its cause. Playwright's public [Error](https://playwright.dev/python/docs/api/class-error)
and [TimeoutError](https://playwright.dev/python/docs/api/class-timeouterror)
contracts expose a message and optional name/stack, not structured launch phases
or durations. Thus this proposal can only classify markers actually present;
it cannot promise to diagnose every future timeout. It would retain the existing
launch timeout, sandbox and single launch, add no version-probe process/timer,
and keep failed browser version unknown. Implementation requires separate
authorization and focused privacy/contract tests against the pinned runtime.

## Authorized prospective launch observations

Implemented after the doc-only repeated-failure record above. The existing
`return_preparation_browser.py` now calls `launch_diagnostics.launch_browser`
once, with the same executable, `chromium_sandbox=True` and `timeout=10000`.
It still enters the existing Playwright context through the same ExitStack,
and the original harness still owns browser cleanup. There is no new process,
probe, timer, retry, sandbox exception or outcome/error-category change.

The fixed `startup_diagnostics` object appears in both the JSON receipt and the
compact stdout summary, on success and failure. It contains the locally installed
numeric Playwright version (otherwise `UNKNOWN`), driver-entry and launch-only
monotonic elapsed milliseconds, the unchanged configured timeout/sandbox, and
whether launch returned. Elapsed values are bounded to 0–600000 for reporting
only; nonfinite measurements are null. The failed browser version remains null:
the Playwright package version is not the Chrome version.

On a Playwright launch exception only, the helper examines at most the first
32768 existing message characters and records truncation. Anchored, fixed
patterns recognize launching/launched/exit records and two stderr markers:
`No usable sandbox!` and `error while loading shared libraries:`. Outputs are
fixed `OBSERVED`/`UNKNOWN` enums and `ZERO`/`NONZERO`/`SIGNAL`/`UNKNOWN` exit kinds.
Unlike the preliminary proposal's `NOT_OBSERVED`, missing markers explicitly
remain `UNKNOWN`: an absent, truncated or changed call-log format cannot prove
that a process did not start. A recorded exit may reflect timeout cleanup.
Neither markers nor exit kinds are asserted as the root cause. Raw messages,
stack/name, stderr, URLs, paths, PID, signal names and command arguments are never
exported. Historical failures remain `ROOT_CAUSE_UNKNOWN`; these observations
cannot retrofit information that their logs did not preserve.

The local inspected Playwright **1.62.0** wheel has these relevant SHA-256 hashes:

| Installed package source | SHA-256 |
|---|---|
| `driver/package/lib/coreBundle.js` | `3258d1cf334c6afc95f22aa9c292436cb976b391e0437f1359c83b84f0cb9d66` |
| `_impl/_helper.py` | `b6a448ddd5f0fbab04872932cdb5d88b35cfa031440fc3a372b29aa1328a7ed9` |
| `_impl/_connection.py` | `1e323ddddbc6fe2c5739760059b6cd5d7cc7b1456547ec8ce44023e4774a9d6e` |

Its process launcher records `<launching>`, `<launched> pid=…`, `[pid=…][err] …`
and `<process did exit: exitCode=…, signal=…>`. The Python error parser appends
formatted call logs to the exception message; these internals are not a stable
public structured diagnostic interface. The focused contract uses the actual
1.62.0 error parser and call-log formatter with synthetic private strings.

Verification: `python -m unittest tests.editorial_workbench.test_launch_diagnostics -v`
passed **12/12**, using the isolated 1.62.0 package. Tests cover private-string
absence, oversize truncation, unknown formats, fixed exit categories, fake-clock
measurements/bounds, identical single-launch arguments, driver failure, same
exception propagation and no journey after timeout, plus actual harness output
wiring. Ruff checks/format checks passed for the three owned Python files.
These tests require no database, browser or external request. No product suite
or workflow was rerun for this change. The next normal integration CI run is
still needed to exercise this observation path with hosted Chrome; any later
success will not establish the historical failure cause.
