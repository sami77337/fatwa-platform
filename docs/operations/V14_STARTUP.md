# V14 P0 — B6 / D6 / FAST9 startup evidence

**ROOT_CAUSE_UNKNOWN.** This lane identifies the B6 failure and subsequent
success, preserves both, and supplies bounded observational code for integration.
It does not fix or explain the historical Chrome failures. A later PASS is not
evidence of causality, permanence, a failure rate, or permission to label a flake.

Base: PR #232, verified GitHub/remote head
`1f08cbb7166f70ec340c495da33ccfc1eda9534e`. Branch:
`codex/20261118-v14-startup`. V13 branch/history preserved. Ownership is only
`tests/v14_browser_startup/**` and this document. No shared browser, workflow,
application, permission or configuration file changed.

## Actual B6 PG17 failure and success on the requested base

| Fact | Failure | Success |
| --- | --- | --- |
| Run / job | [44228655470 / 134547992648](https://github.com/sami77337/fatwa-platform/actions/runs/44228655470/job/134547992648) | [44228663469 / 134548019306](https://github.com/sami77337/fatwa-platform/actions/runs/44228663469/job/134548019306) |
| Event / attempt | push / 1 | pull_request / 1 |
| Run head AND logged checkout | `1f08cbb7166f70ec340c495da33ccfc1eda9534e` | same exact SHA |
| Browser report UTC | 2026-11-18 03:12:58.2878099 | 2026-11-18 03:13:30 (see exact excerpt) |
| Browser outcome | BLOCKED; 0 PASS, 0 FAIL, 10 NOT_RUN, 0 SKIP | PASS; 10 PASS, 0 FAIL, 0 NOT_RUN, 0 SKIP |
| Mandatory Python gate | FAIL, `AssertionError: 2 != 0` | PASS |
| Observed blocker | `Timed out: DevTools launch` | no blocker |
| Chrome version probe | 157.0.8103.50 | 157.0.8103.50 |
| Browser.getVersion session | absent | Chrome/157.0.8103.50 |
| Node / Python | 24.22.2 / 3.13.18 | same |
| Actual PostgreSQL in container log | 17.12 | 17.12 |
| Runner / image / provisioner | 2.338.2 / ubuntu-26.04 20261111.196.1 / 20261103.629 | same |
| Kernel / region | 7.0.0-1019-azure / westus | same kernel / centralus |

These are **two independently triggered runs**, created four seconds apart; they
are not an automatic retry pair. Success does not erase the failed push check.
The earlier PR-only query returned successful PR runs and missed this push run.
The connector's general GET of `/actions/runs?branch=...` exposed both events;
`/actions/runs/{id}/jobs?filter=all&per_page=100` also permits historical attempts.
No rerun was requested. The initial shell `gh api` read returned Forbidden;
the authorized connector read resolved job discovery without changing settings.

The failure completed five asset preflight checks, but all ten browser cases
remained NOT_RUN. The separate Chrome `--version` probe does not prove the
attempted browser process reached CDP. Empty requests/errors arrays at this point
do not prove a successful journey or application safety.

## What the B6 code and evidence establish

Inspected `tests/acceptance/wave6/browser.mjs`, its `test_browser.py`, the existing
D6 `tests/acceptance/fastbuild/startup.mjs`, research bridge startup reporter,
and FAST9 `tests/editorial_workbench/launch_diagnostics.py` and its calling harness.

B6 directly spawns sandboxed Chrome, then calls `until(..., "DevTools launch")`.
That poll has an unchanged **12000ms wall-clock limit** and 50ms polling pause.
It checks launch errors/process exit, reads `DevToolsActivePort`, and returns when
the first line converts to a truthy number. Its catch currently makes any read
exception another unsuccessful poll. Therefore this failure means the poll did
not observe a usable value before its limit; it does **not** distinguish absent
file, incomplete contents, other read error, Chrome delay, or scheduler delay.
The historical logs do not measure actual per-phase or total startup durations.
Do not manufacture a 12000ms measured elapsed value from the configured limit.

After that poll B6 fetches the target list and opens a WebSocket. Neither step
shares the poll deadline in this legacy harness; the enclosing Python subprocess
has a 240-second bound for the entire browser command. Do not describe B6 as
having D6's single bounded 30-second startup. This lane changes neither bound.
Any convergence on the existing ProtectedBrowser needs a separately reviewed,
coordinated shared-file change, preserving sandbox, network guards and failures.

The failed artifact `b6-postgres-17`, ID `14394031546`, is listed as 12766 bytes,
digest `sha256:4b6dba392b6ebb04e5faf27dc27cc5318a79d49d11f948d9eaa8fc4c4d4d7297`.
The connector returned an archive download, but this environment's download
tunnel returned **403 Forbidden**. Its ZIP bytes/browser-result.json were not
inspected. In particular no D-Bus or raw stderr diagnosis is claimed for this job.

## Historical comparison, without conflating boundaries

| Evidence | Established observation | Unestablished inference |
| --- | --- | --- |
| B6 [134531410766](https://github.com/sami77337/fatwa-platform/actions/runs/44223649042/job/134531410766), `38cd137db50cc95ae53fa275b5d90b8274096e5d` | Same port-poll timeout, BLOCKED / 10 NOT_RUN, 2026-11-18 02:31:05; actual log fetched | Same root cause as latest B6 |
| B6 [121539817683 failure](https://github.com/sami77337/fatwa-platform/actions/runs/40313379288/job/121539817683), [121540916296 success](https://github.com/sami77337/fatwa-platform/actions/runs/40313379288/job/121540916296), `2eda8b9ed464cced7dfd54644403c3b346d01e0a` | Attempts 1/2; 2026-10-26; same port-poll failure then 10 PASS. Chrome155.0.8059.39, Node24.21.0, PG17.11. Both actual logs fetched | A Chrome157-only regression, or proof that retry repairs a cause |
| D6 [134488475034 failure](https://github.com/sami77337/fatwa-platform/actions/runs/44210846285/job/134488475034), [134490343087 success](https://github.com/sami77337/fatwa-platform/actions/runs/44210846285/job/134490343087), `5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8` | WebSocket terminal stage, 30001/30000ms shared startup, NOT_RUN; later READY at642ms. Previously fetched full logs re-parsed here | That WebSocket itself took all30 seconds; same cause as B6's earlier port-file boundary |
| FAST9 [134512970271](https://github.com/sami77337/fatwa-platform/actions/runs/44218120292/job/134512970271) | Re-fetched actual log: `browser_startup`, TimeoutError, `playwright_timeout`, harness line352 (`chromium.launch`); actual merge checkout `5a5526f4ad929b71e21faefa083c8f7316f46733` | Missing browser process, sandbox fault, WebSocket timeout, or a cause from later success |

`git diff 2eda8b9..1f08cbb -- tests/acceptance/wave6/browser.mjs` is empty:
the inspected B6 source is identical between those endpoints. This is a code
comparison, not evidence of identical machines, Chrome, resources or causality.

[V13 D6 analysis](V13_D6_ANALYSIS.md) and
[V13 FAST9 analysis](V13_FAST9_STARTUP.md) remain valid historical boundaries.
FAST9's comparison successes used different merge checkouts; do not turn those
into a same-SHA experiment. Re-fetched FAST9 decoded normalized log SHA-256:
`f6ae7a583f3bd062bfc8c0ddff05422867a6d5ba78a50dd710a4e9cc6e4fd9e8`.
The V13 document's BOM-preserving hash is a different normalization, not a conflict.

No CPU, memory, file-descriptor, event-loop or host-load evidence proves a common
cause. Worker/region differences are observations only. No security vulnerability
was established by these logs; no security/rights check was relaxed.

## Deliverables and integration contract

`analyze_b6.py` checks checkout AND report SHA, one scoped browser command/report,
duplicate JSON keys, case/count agreement, precise failure boundary and mandatory
exit evidence. It emits an allowlist projection with no raw log/path/URL/error
text. Both outcomes and unknown cause remain present. Inputs are bounded at2MiB.
It reuses the existing V13 text normalization/error helpers, not browser logic.

`evidence/manifest.json` records five exact jobs, run/event/attempt, decoded full
log hashes, selected original line numbers, excerpt hashes, and checked
projections. Excerpts contain only synthetic historical diagnostics. They are
excerpts, not full-log/ZIP archives; tests cannot authenticate GitHub independently.
Latest normalized full log SHA-256 values:

- Failed134547992648: `651293517c08d6b75fc42d86d8e6984b78c4471ea303ab37892accf291f4cd4e`.
- Passed134548019306: `45301fbf90beaadde36d5a91da6ef4fceb9f91144f0af0c2ba0a362691b1cb52`.

`b6_observations.mjs` exports `B6StartupObservations`. This is **not wired into
B6 yet**: shared files belong to the integrator. The helper performs no spawn,
I/O, timer, retry, timeout adjustment or exception-policy change. It records a
fixed one-way phase sequence and fixed event names, monotonically measured
durations capped for reporting at600000ms, counts capped at10000, and null for
unavailable timing. Missing events mean "not observed", not "did not happen".
`snapshot()` freezes startup facts before cleanup; caller mutation cannot change
later snapshots. Unknown input names/text cannot be serialized. It never accepts
stderr, paths, URLs, PIDs, environment dumps, stack traces or CDP payloads.

Integrator-owned insertion points in `tests/acceptance/wave6/browser.mjs`:

1. Construct after asset preflight, just before the existing spawn. Record
   `phase("spawn")`; add observational `spawned`, `spawn-error`, `process-exit`
   events without replacing existing error or exit handling.
2. Before the unchanged `until` call record `phase("port-file")`. Within its
   existing read/catch record `port-missing` (ENOENT), `port-read-error` (other
   read errors), `port-incomplete` (nonusable current value), or `port-ready`
   (current predicate succeeds). Preserve the current return/throw behavior.
3. Immediately before existing target fetch record `phase("target-discovery")`;
   record `target-response` only after that operation returns. Before constructing
   the existing socket record `phase("websocket")`. Observe its open/error/close
   events; keep all original resolution/rejection semantics.
4. Capture `snapshot("READY")` immediately after socket startup, before any
   `Browser.getVersion`/interaction; on startup failure capture
   `snapshot("BLOCKED")` before cleanup. Preserve the original BLOCKED/exit2 and
   Python FAIL gate. Attach the fixed `startup_observations` object to the report
   AND `E6_BROWSER_EVIDENCE` stdout. Do not export new raw stderr or error strings.
5. D6 already has V13 per-phase/supervisor/WebSocket startup-only snapshots;
   FAST9 already has V13 driver/launch elapsed times and bounded fixed Playwright
   markers. Reuse those observations; do not introduce a parallel launch service.
   An exit marker may be timeout cleanup rather than a causal precursor.

CI wiring request: run the12 new Python evidence tests and6 Node observer tests
explicitly. After shared B6 wiring, the integrator should run the affected B6
browser case once on each PG17/18 protected Chrome environment and verify the
new stdout/artifact field on success plus a deterministic synthetic failed
startup. A fake event/clock test is not a hosted Chrome failure reproduction.
No loop/retry campaign or whole-product suite rerun is requested here.

## Focused validation and limits

- Node24.19.0:6/6 observer tests PASS; fixed phases, privacy, bounded numeric
  fields, unknown clocks, immutable startup snapshots, duplicate/out-of-order calls.
- Python3.13.16:12/12 evidence tests PASS on each fresh owned PG17.12 and PG18.7
  helper environment. `SHOW server_version_num` returned170012 and180007.
  These are **offline diagnostic tests with a read-only database version check**,
  not product/database/browser acceptance. No application migrations ran.
- Ruff check/format PASS. Early local lint/format issues were corrected before
  final checks. The first temporary excerpt-generation invocation lacked
  PYTHONPATH, and the next omitted the standalone success summary; both were
  corrected before generating/verifying the committed five excerpts.
- No product suites, live Chrome journey, provider calls or external sends were
  rerun. Runtime instrumentation integration and archive-byte inspection remain
  outstanding; root-cause attribution is UNKNOWN, not a blocked-code repair claim.

```sh
node --test tests/v14_browser_startup/b6_observations.test.mjs
.venv/bin/python -m unittest tests.v14_browser_startup.test_evidence -v
.venv/bin/python -m tests.v14_browser_startup.analyze_b6 \
  /path/to/134547992648.log /path/to/134548019306.log \
  --sha 1f08cbb7166f70ec340c495da33ccfc1eda9534e

# Actual focused runs used these two local, isolated server installations:
.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /tmp/v9-pg/root/usr/lib/postgresql/17/bin --major 17 --no-bootstrap \
  -- .venv/bin/python -m tests.v14_browser_startup.verify
.venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /tmp/v12-pg18/install/bin --major 18 --no-bootstrap \
  -- .venv/bin/python -m tests.v14_browser_startup.verify
```

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. Leadership83%±9
is unchanged and is not acceptance. No main merge, settings changes, production,
real data/keys/messages, U03 grants, automatic fatwa approval, or Meta contracts.
