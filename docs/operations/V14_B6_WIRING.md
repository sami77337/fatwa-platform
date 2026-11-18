# V14 B6 startup observer integration

The shared B6 entrypoint now records the delivered `B6StartupObservations` at
its existing spawn, port-file, target-discovery and WebSocket boundaries. The
same fixed object is written to `browser-result.json` and `E6_BROWSER_EVIDENCE`.
READY is frozen immediately after the socket opens, before Browser.getVersion
and interactions. A startup failure freezes BLOCKED before cleanup. A later
failure after socket readiness does not rewrite that earlier startup snapshot;
READY is not a product journey PASS.

No launch flag, sandbox behavior, port parsing predicate, exception propagation,
retry, timeout or cleanup behavior changes. The existing port poll stays12000ms
with50ms polling; target discovery and socket retain their old semantics.
Fixed event names distinguish observed ENOENT, other read error, incomplete port,
process spawn/exit, target response and socket open/error/close. The observer
accepts no raw stderr, paths, URLs, PID, secret or CDP payload. Existing legacy
report fields are not expanded. Frozen observations ignore cleanup events.

## Focused evidence

Node24.19.0, on the integration code in this isolated worktree:

- Six delivered observer contract tests PASS.
- Three new **actual entrypoint** failure probes PASS. They run the original
  `tests/acceptance/wave6/browser.mjs` against a bounded local preflight fixture
  and the existing E6_BROWSER executable seam. They exercise spawn ENOENT,
  one complete unchanged12-second port-file timeout, and successful port/target
  reads followed by missing page-target failure. Each preserves BLOCKED/exit2,
  five successful asset preflights, all ten browser cases NOT_RUN, no retries,
  identical stdout/artifact observations, and private-safe observer fields.
- The port-timeout probe proves the snapshot still has no process-exit event
  after cleanup terminates the synthetic process. This is a deterministic
  synthetic diagnostic, **not reproduction of the hosted Chrome root cause**.
- Combined9/9 Node checks PASS,18.727s. Twelve offline Python evidence checks
  PASS,0.004s; no product suites or PostgreSQL queries were rerun here.
- `node --check` and `git diff --check` PASS.

Initial new-probe run:3/3 failed because the test fixture expected the ten-case
review-batch configuration but omitted E6_REVIEW_BATCHES=required, producing
nine NOT_RUN cases. The fixture now explicitly selects the same review-batch
configuration as B6 CI; the ten-case assertion and mandatory exit2 are unchanged.
The corrected three probes and six observer checks passed. No product protection
or startup deadline was changed to repair this fixture error.

## Integrator verification

Run the new diagnostic wiring and delivered observer tests explicitly:

```sh
node --test tests/v14_browser_startup/b6_wiring.test.mjs tests/v14_browser_startup/b6_observations.test.mjs
python -m unittest tests.v14_browser_startup.test_evidence -v
```

The existing B6 matrix owns the fresh synthetic PostgreSQL17/18 databases and
protected Chrome. Its affected browser stage remains:

```sh
python tests/acceptance/wave6/run.py --browser --review-batches
```

Keep E6_SYNTHETIC_ONLY=1, the guarded e6_synthetic/test_e6_synthetic database
names, E6_BROWSER=/usr/bin/google-chrome and the existing ephemeral credentials.
The integrator's Python gate should require the successful artifact's observation
schema, READY, four phases, websocket-open event and unchanged12000ms poll bound.
No protected Chrome run is claimed by this internal wiring lane; final-head
PG17/18 hosted results must be reported separately.

[Historical failure and source limits](V14_STARTUP.md) remain unchanged:
ROOT_CAUSE_UNKNOWN, push and PR runs are distinct, ZIP bytes were not inspected.
No new engineering estimate, acceptance or production authorization. Gate B
NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
