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

## Preserved hosted V14 failure — 2026-11-18

The newly wired observer recorded an actual hosted failure on
`8329364173bde5e76d1a96931cd71dd31fb255d4`, independently fetched from
[push run44235373603, PG18 job134570116361](https://github.com/sami77337/fatwa-platform/actions/runs/44235373603/job/134570116361).
The run metadata identifies push/attempt1, created04:09:38Z; the logged checkout
and E6 evidence SHA both match that head. The container log reports PostgreSQL18.7;
the browser version probe reports Google Chrome157.0.8103.50. The probe is not a
successful CDP session. No workflow rerun was requested by this diagnostic task.

The E6 browser command was **BLOCKED**, `Timed out: DevTools launch`:0 PASS,
0 FAIL,10 NOT_RUN,0 SKIP. Its mandatory Python gate failed with returncode2
(`AssertionError: 2 != 0`), followed by the workflow step exit1. All five asset
preflights passed, but no browser interaction ran.

The frozen startup observations now establish more than the older plain timeout:

| Observation before cleanup | Actual value |
| --- | --- |
| Monotonic startup elapsed |12035ms|
| Spawn phase |3ms|
| Port-file phase |12032ms|
| Spawn event |1, first at4ms|
| Port-file ENOENT observations |239, first at4ms|
| Incomplete-port / other-read-error observations |0 /0|
| Port-ready / target-response / websocket-open |0 /0 /0|
| Spawn-error / process-exit observations |0 /0|
| Configured port poll limit |12000ms, unchanged|

This shows that the poll repeatedly observed a missing port file and did not
observe a process exit before its frozen boundary. It does **not** establish
why Chrome had not provided that file, whether host load/sandbox/device resources
were causal, or a common cause with D6/FAST9. Zero interaction requests/errors
with ten NOT_RUN cases cannot be interpreted as product safety or a successful
journey. **ROOT_CAUSE_UNKNOWN remains the result.**

A later independently triggered [push run44235894394](https://github.com/sami77337/fatwa-platform/actions/runs/44235894394)
has metadata conclusionSUCCESS, attempt1, created04:14:05Z, at
`32cfcb7f3a59b04e153dca2a627da21e9b29f739`. That is a **different SHA**, not a
same-head retry or proof that the earlier underlying cause was repaired. This
follow-up inspected the later run metadata, not its complete job logs; separate
integration evidence owns its product/browser execution claims. The earlier
failed run remains failed.

The safe eight-line [excerpt](../../tests/v14_browser_startup/evidence/v14_8329364.excerpt.log)
and [manifest](../../tests/v14_browser_startup/evidence/v14_8329364.manifest.json)
preserve original selected line numbers, run metadata, the decoded normalized
full-log hash and the exact observer projection. Decoded normalized log UTF-8:
149631 bytes, SHA-256
`ccf0ad47751b63673cc6de1be69f9e01e50e79cf284b8fa42812d6aea16faf2c`.
Excerpt SHA-256:
`6164ddf2f2f6b5b977f8396f410c77bc07ea939a56c7301820fcc6f4df3effee`.
Normalization removes the connector's leading BOM and maps CRLF to LF while
preserving its final newline. These are decoded-text hashes, not ZIP byte hashes.
No artifact archive was downloaded or inspected in this follow-up. Original
historical ZIP403 limits remain. No product test rerun, launch/timeout/retry
change, acceptance, new percentage or production/GitHub-settings change occurred.
