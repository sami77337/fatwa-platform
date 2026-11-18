# V13 startup diagnostic assertion: fractional timer boundary

Base: `09cc55aa021660f593bb1b70e850d0f448ddad3a`. This change is restricted to
`tests/acceptance/fastbuild/v13_diagnostics.test.mjs` and this evidence note.
No browser runtime, timeout, sandbox, retry, failure classification, product
service, or GitHub setting was changed.

## Observed CI failure

[V13 run 44221424598, PG17 job 134523957084](https://github.com/sami77337/fatwa-platform/actions/runs/44221424598/job/134523957084)
reported `STARTUP-LIFECYCLE EXIT=1`: 8/9 lifecycle tests passed. At
`2026-11-18T02:12:14.7149719Z`, the failure points to diagnostics test line 90,
the strict comparison of `websocket.remaining_ms` with zero: actual `1`, expected
`0`. The reported 1608.021668ms is the entire test duration, including cleanup;
it is not the `performance.now()` startup interval being asserted.

Before that assertion, the test had already verified zero journey invocations,
`NOT_RUN`, `BROWSER_STARTUP_TIMEOUT`, terminal stage `websocket`, successful
cleanup, fixed telemetry shape/privacy, the earlier 400ms port delay, and its
contribution to the shared budget. This failure does not establish that the
browser journey ran or that the runtime extended its deadline.

## Deterministic reproduction before editing

On Node `v24.19.0`, invoking the existing production measurement method with
explicit fractional monotonic samples reproduced the exact failing assertion:

```javascript
const browser = new ProtectedBrowser({startupTimeoutMs:1600});
browser.startupStarted = 5000.75;
browser.startupPhase = {name:"websocket", started:5500.75};
browser.startupTimings = {};
browser.finishStartupPhase(6600.0);
// startup elapsed = round(6600.0 - 5000.75) = 1599
// remaining = round(1600 - (6600.0 - 5000.75)) = 1
assert.equal(browser.startupTimings.websocket.remaining_ms, 0);
// AssertionError: 1 !== 0
```

This is a deterministic reproduction of the diagnostic/assertion mismatch,
not a claim to reproduce the precise hosted worker's event-loop scheduling.
The failed CI log does not include its fractional clock samples.

[Node's timer contract](https://nodejs.org/api/timers.html#timers_settimeout_callback_delay_args)
does not guarantee exact callback timing. [libuv's loop clock](https://docs.libuv.org/en/v1.x/loop.html#c.uv_now)
uses a cached millisecond timestamp, and its documentation distinguishes this
from sub-millisecond time. The runtime diagnostic uses fractional
`performance.now()` samples and independently rounds durations and remaining
budget. Requiring those observations to equal an exact zero at the callback
asserted precision that this combination does not promise. The production
remaining-budget calculation is retained rather than clamping evidence to zero.

## Focused correction and verification

- Allow **at most one reported millisecond** in the remaining-budget assertion,
  and the corresponding 1599ms rounded lower boundary for this 1600ms fixture.
  The existing 4000ms test completion bound is unchanged. This observation
  allowance neither reschedules nor adds time to the runtime timer.
- Retain the failure code/stage, no-journey, cleanup, phase attribution and
  privacy assertions. Add observation of the actual global timer registration:
  exactly one 1600ms startup timer must be scheduled; a phase reset/retry is
  rejected. The observer forwards each original callback/delay unchanged.
- Add a deterministic regression using `finishStartupPhase()` itself. It accepts
  the fractional example and rejects both a two-millisecond remaining gap and
  an elapsed value of 1598ms. This is a narrow measurement allowance, not a broad
  pass for arbitrary early aborts.

Executed once after the correction:

```sh
FATWA_FASTBUILD_PYTHON=/workspace/fatwa-platform/.local/venv/bin/python \
node --test tests/acceptance/fastbuild/v13_diagnostics.test.mjs \
  tests/v13_browser_startup/startup_contract.test.mjs
```

**10/10 PASS**, no skipped/cancelled tests, 4129.652128ms, Node `v24.19.0`.
Local output: `/tmp/v13-diagnostic-assertion-tests.log`. The count is the prior
nine lifecycle cases plus the new deterministic regression. These tests use
synthetic loopback peers; this is not Chrome/product acceptance or a PostgreSQL
test claim. `node --check` and `git diff --check` pass. No unrelated passing
product suites were rerun and no workflow rerun was requested.

The separate historical D6 and FAST9 browser startup incidents remain
`ROOT_CAUSE_UNKNOWN`. This verified assertion defect is not evidence of their
cause and does not convert either historical browser failure to a pass.
Gate B `NOT_PASSED`, C/D/E `HOLD`, Phase01 `BLOCKED`, `NOT_DEPLOYED` unchanged.
