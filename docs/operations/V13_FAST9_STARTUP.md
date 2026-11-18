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
