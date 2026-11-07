# 02-E6 local startup investigation — 2026-10-29

Result: **diagnostic ambiguity demonstrated; PG17 root cause UNKNOWN**.
Only `startup.test.mjs` and this note are added. The launcher, fixtures, database
guards, deadlines, sandbox flags, workflows and existing evidence are unchanged.

## Inspected identity and contracts

- Local HEAD: `0769f66e93fdf710ca55e9e68e87430a93f14c40` (FAST8, detached).
- Locally pinned `refs/remotes/origin/fast9-v5-review-pr152` through `pr159`
  have no differences from that baseline in `tests/acceptance/wave6/` or
  `.github/workflows/b6-integration.yml`. They were read locally, not integrated.
- `browser.mjs` Git blob: `a863c4d6e94b76b5ca2a521312feecef363cb59e`.
  Original CRLF working-file SHA256:
  `26b2b0e415705cd2f80a649a178fba5f7a7c6f13549e1c5fc912fe5bccb68292`.
- `support.py` Git blob: `afc2d100fdac6b42a363b5f15ac7fedeb4f5dbf1`.
  Original CRLF working-file SHA256:
  `48cdb975fa1c44bb9e8af72d7d2b90b69d693a47a1c170fb407ccdeb90c71c3b`.

B6's PG17 and PG18 matrix invokes the same Wave6 command,
`run.py --browser --review-batches`, with `/usr/bin/google-chrome`.
`run.py` requires Python 3.13 and calls `require_disposable_database()` before
Django setup/test database lifecycle. `test_browser.py` seeds the synthetic
catalog and requires Node exit code zero (subprocess timeout: 240 seconds).
The fixture is `wave6-e6-synthetic` / `e6-fabricated` / `e6-synthetic-only`,
input `generated-e6-not-owner-source`: 47 fabricated headings, two roots, depth
two. Its repeated a/b/c hashes are synthetic placeholders, not source evidence.
No fixture was seeded in this investigation.

The actual browser entry point checks the literal loopback origin, Node 24,
inventory namespace/count and five asset status/MIME/byte checks before spawn.
It uses a fresh profile, enabled sandbox, loopback debugging and port zero.
`until()` (line 34) polls every 50 ms while `Date.now() < deadline`, default
12000 ms. The startup block (lines 231–244) rejects observed spawn errors or
child exit/signal before reading the first line of `DevToolsActivePort`.
Any read exception is caught and converted to `false`; an empty, zero or
non-numeric first line also continues polling. No PostgreSQL-major branch
exists in this startup block.

## What the deterministic tests establish

`startup.test.mjs` evaluates the unchanged full `browser.mjs` and its two actual
relative imports using Node VM modules. All child-process calls, filesystem
effects, HTTP, WebSocket and time are replaced by local in-memory fixtures.
The only real file reads are those three JavaScript source files. Inventory
and asset responses are fabricated to reach startup, not tested against a
server. Reports are captured in memory and never written as acceptance evidence.
Test fixture identity (`startup.test.mjs`, UTF-8/LF SHA256):
`f1bd3164c925716ece280cd153fb451796e97189eb30d6256aef85a2915cb8f7`.

Seventeen negative/regression cases cover:

- ENOENT, EACCES and EISDIR all produce the same `Timed out: DevTools launch`:
  240 immediate virtual reads, at 0 through 11950 ms, then timeout at 12000 ms.
  Thus the historical timeout alone does **not** prove the file was absent.
- Empty, non-numeric and zero port records cannot become browser acceptance.
- A valid record at 11950 ms reaches **mocked, deliberately failing** target
  discovery; one available only at 12000 ms is never read. This illustrates a
  deadline boundary, not evidence that the historical file arrived late.
- Child exit, signal and spawn error stay blocked, without another spawn.
- Stderr is bounded and the temporary profile path is redacted. Synthetic
  D-Bus text does not become a causal diagnosis.
- Wrong namespace/count or asset status/MIME/bytes fails before spawn.

Startup negatives assert `BLOCKED`, exit 2, ten journey cases `NOT_RUN`, zero
PASS/FAIL/SKIP cases, no screenshots/interaction requests, and source/assembled/
review-batch acceptance `NOT_RUN`. Preflight negatives assert `FAIL`, exit 1,
with the same unexecuted cases. These nonzero exits still fail the mandatory
Django browser gate. Cleanup assertions verify calls on mocks only; they do
not prove real Chrome process-tree cleanup or Windows/Linux behavior.

## Executed offline checks

Windows; Node `v24.16.0`; Python `3.13.15`; installed Django `5.2.18`.
No installation, browser, server, database connection or network request.

| Command | Actual result |
| --- | --- |
| `node --experimental-vm-modules --test tests/acceptance/wave6/startup.test.mjs tests/acceptance/wave6/cdp.test.mjs` | Exit 0; 23 passed (17 new + 6 existing), 0 failed/cancelled/skipped/todo |
| `python -B -m unittest tests.acceptance.wave6.test_guard -v` | Exit 0; 6 passed, 0 failed/skipped; settings patched in memory |
| `node --check tests/acceptance/wave6/startup.test.mjs` | Exit 0 |
| `git diff --exit-code` and `git diff --check` | Exit 0; no tracked files changed |
| `git diff --no-index --check -- NUL <new-file>` for each of the two new files | Exit 0; no whitespace errors |

Post-test SHA256 checks matched both original source hashes above, including
303 CRLF lines in `browser.mjs` and 55 in `support.py`. `git status --short
--untracked-files=all` listed only the two new files in the owned directory.

Node prints its expected VM Modules experimental warning. The switch enables
the test-only module API; it does not change browser flags or system settings.
No test failed. An exploratory `rg` command using a Windows path wildcard
(`docs/dev/FAST8*`) reported invalid path syntax; the corrected `-g '*FAST8*'`
search yielded no matching evidence. `git diff --no-index --stat -- NUL ...`
returned 1 because the new test file differs from an empty file, not a test failure.
One documentation patch was rejected for a mismatched context before writing;
the corrected patch succeeded. Git warns that the two new LF files would be
converted to CRLF on a future Git write; original files were not rewritten.

## Unresolved evidence and next local action

The reported PG17 BLOCKED / PG18 passed pairing is task context, not a freshly
verified CI result. Exact paired raw `browser.log`, `browser-result.json`,
runner/browser versions, resource/exit timeline and port-file observations
were not available in the inspected worktree. The tracked baseline report
at `docs/dev/e6/artifacts/baseline/browser-result.json` belongs to
`b5de539237de0cd12b91b0705a3cb92014bfe98b` and describes an early sandbox exit,
not this 12-second timeout. The FAST7BC integration note documents a prior
intermittent startup failure and explicitly does not establish D-Bus as cause.
Neither is substituted for the missing paired evidence.

Possible late startup, an unreadable/invalid port file, runner scheduling,
browser/environment differences or other causes remain unproven. The loop's
deadline is also not a hard bound on an in-flight `readFile`; the following
target fetch and WebSocket open have no local timeout. The virtual tests do
not diagnose real I/O stalls. The separate fastbuild/Wave7 startup helper and
process/HTTP fixtures are not used by Wave6 and were not executed or imported.

Next local action: inspect a supplied matched pair of raw PG17/PG18 startup
artifacts against their exact SHA and environment, then decide whether a narrow
diagnostic change is justified. No timeout increase, retry, sandbox relaxation
or launcher fix is supported by the current evidence. The new test command is
explicit/local; existing CI registration is unchanged.

**NOT_RUN:** real browser acceptance, PG17/PG18 execution, database setup or
migrations, full suite, CI, owner/source acceptance and complete-history proof.
No push, PR, merge, deployment or remote mutation was performed.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.

## Follow-up on 2026-11-06

The earlier sections record the recovered October 29 investigation against the
original launcher. Its 17 mocked cases passed again before editing the launcher.
This follow-up extends that fixture and instruments the Wave6 acceptance harness.

Both original [PG17](https://github.com/sami77337/fatwa-platform/actions/runs/40471061183/artifacts/12718349077)
and [PG18](https://github.com/sami77337/fatwa-platform/actions/runs/40471061183/artifacts/12718950224)
archives were read. Their SHA256 digests match the run manifest respectively:

- PG17 `5d96799bcae65c5c72b0cf2c840e5182addfa4b9ea2d9c26a06f5b0741eb7c50`
- PG18 `d329ad1990e52ab3bfaef4dcabc41617a01b1f5662904c68555b038e37cffbb6`

At commit `2d5cc49f883bf5611d7d64dca5c61696a16b7a08` the reports match on
Node v24.21.0, Chrome 155.0.8059.39, Linux 7.0.0-1017-azure x64 and five
successful asset checks. PG17 had ten unexecuted journeys and four D-Bus
stderr messages. PG18 passed ten journeys. Neither artifact records port-file
states and their timing; the underlying reason for the difference is unknown.

The harness now snapshots the startup stage, monotonic elapsed time, child PID,
observed exit status or signal, and spawn, exit and close times when observed.
For the port file it records the number of polls, time of first observation for
each fixed category (missing, read error, empty, invalid, valid), the last
category and last read error code. It omits port numbers, raw content and
DevTools IDs from these fields. Numeric port validation now rejects non-decimal
and out-of-range values. A profile-removal error retains the initial result and
the diagnostic snapshot, and exits with failure. The 12-second port wait and
the actual browser assertions remain in effect.

For a future authorized synthetic run, compare the two jobs' `startup` records
under the same versions and fixture. A recorded child exit before a usable port
supports early termination. Repeated EACCES or invalid contents distinguish
file-access or formatting problems. Only ENOENT observations until the deadline
establishes that the polling process did not find the file; OS scheduling and a
late or stalled browser would still require additional evidence. Report missing
data explicitly when a subprocess reaches the outer deadline before reporting.

Focused validation on Linux with Node v24.22.1 and Django 5.2.18:

- `node --experimental-vm-modules --test tests/acceptance/wave6/startup.test.mjs tests/acceptance/wave6/cdp.test.mjs` passed 27/27 (21 startup and six CDP), zero skips or todos.
- `python -B -m unittest tests.acceptance.wave6.test_guard -v` passed 6/6 with Python 3.13 and mocked Django settings.
- `node --check` on the launcher and its startup test, and staged `git diff --check`, passed.

The mock suite includes four follow-up cases. Two initially failed against the
original launcher; one additional cleanup case failed before the evidence write
was fixed. No Chrome process, database or CI job was started by these checks.

### Bound discovery and the WebSocket handshake

The PR #161 head `a867e34507769e8abc847ef1baf62dc403f91301` could wait past the port deadline on an in-flight read, a stalled target-list response or a WebSocket that closed before opening. Its target discovery also followed HTTP redirects and accepted a debugger URL on another host or port. The virtual launcher tests reproduced these paths with in-memory fixtures. No foreign network connection was attempted.

The port-file read, HTTP target discovery and WebSocket opening now share one 12-second deadline starting at browser spawn. Discovery requires HTTP 200 and an exact `ws://127.0.0.1:<discovered-port>/devtools/page/<id>` target. Early close or error produces a blocked startup report and enters cleanup. Existing CDP commands retain their own 10-second deadlines. No new launch attempt or application retry is added.

On Node 24.22.1 the original launcher passed its 21 startup checks and failed all nine new regressions. The revised launcher passed all 30 startup checks and six CDP tests. The six offline Python guard tests passed separately. These checks do not identify the cause of the earlier PG17 port-file timeout. The focused run did not start a database or a real browser.

### Complete port records, 2026-11-07

A focused reproduction on `02b14c52` exposed a premature HTTP request. When a read returned only `9` while the profile file was being written, the launcher attempted discovery on port 9. With a valid port and a missing or malformed browser path, it also entered discovery immediately. The launcher now waits within its existing deadline for a valid port and the `/devtools/browser/<id>` line, matching the protected Fastbuild reader's record shape. Diagnostics distinguish a missing second line as `partial`. Raw record contents remain outside the report.

Four new tests failed before the change. The revised launcher passed 34 startup tests and six CDP tests, plus six mocked Python guards. A delayed complete CRLF record triggered exactly one discovery request, on its final port. Missing or invalid browser records exhausted the existing 12-second budget with zero discovery requests. The failed #167 PG17 artifact had empty browser stderr and no startup probe, so it cannot establish whether this condition occurred in that run.
