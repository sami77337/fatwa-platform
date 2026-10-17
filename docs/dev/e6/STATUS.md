# E6 first usable increment

Base: `b5de539237de0cd12b91b0705a3cb92014bfe98b`, branch
`codex/20261017-wave5-review-worklist`. Lane branch:
`codex/20261017-wave6-e6`. Only E6 paths changed.

## BOOTSTRAP_STATUS

- Selected environment ID:
  `ccarenv_b64_Y2NhcmVudl85NWQ3YTVkMmFkMDg4MTkxOTA1YmVlNmNlODEzYzliNQ`.
  Host startup tool returned `ready`; Cloud published status is supplied by the
  delegation, not independently exposed by a management API. Workspace:
  `/workspace/fatwa-platform`. No DigitalOcean/owner desktop used.
- Task URL/ID: NONE exposed to this worker. Source delegation thread:
  `01a1173c-6c30-723a-828d-8948d842003d` (not a Cloud task URL).
- E6 running, other lane task states/concurrency NOT_OBSERVED. One worker
  observed in this lane; quota/usage NOT_OBSERVED. No additional agents spawned.
- Repository remote verified; exact base fetched. Local and remote E6 branch
  absence checked before creation. Git push dry-run succeeded. `gh` reported
  its token invalid; no credential change/request/retry performed. Publication
  uses already functioning Git transport and the connected GitHub PR tool.
- Runtime: Python 3.13.5 (`/usr/bin/python3.13`, uv venv), uv 0.12.23,
  Node v24.19.0, Linux 6.18.44 x64, Chromium 154.0.8037.57 Debian 13.
- Disposable PostgreSQL 18.6 Docker service `fatwa-e6-synthetic`, loopback
  55466, database `e6_synthetic`, test database `test_e6_synthetic`.
  Image `postgres:18-bookworm` resolved digest
  `sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c`.

## Verified results

Commands below use the explicit disposable environment in README.

| Command | Actual outcome |
| --- | --- |
| `node --test tests/acceptance/wave6/cdp.test.mjs` | 6 PASS, 0 FAIL, 0 SKIP |
| `.venv/bin/python -m unittest tests.acceptance.wave6.test_guard -v` | 6 PASS, 0 FAIL, 0 SKIP; no DB |
| `.venv/bin/python tests/acceptance/wave6/run.py` | 8 PASS, 0 FAIL, 0 SKIP; real PostgreSQL/migrations |
| `.venv/bin/python tests/acceptance/wave6/run.py --regressions` | 1 FAIL, 0 PASS, 0 SKIP; confirmed E4 defect |
| `.venv/bin/python tests/acceptance/wave6/run.py --browser` | 1 Django gate FAIL because Node returned 2 (BLOCKED); 0 browser cases passed/failed, 9 NOT_RUN, 0 SKIP |
| `node --check tests/acceptance/wave6/browser.mjs` | exit 0; syntax only |

Initial service test run: 5 PASS / 3 FAIL because Django Client used `testserver`
while review views require loopback host **and** peer. Correcting only the
E6 client's HTTP_HOST to `127.0.0.1` produced 8/8 GREEN. No product fix claimed.
Baseline browser report records the base SHA plus uncommitted E6-only paths;
it does not claim the new harness was already committed at that SHA.

## Open defects / blocked gates

**E4 minimal repro, real PostgreSQL:** seed the E6 fixture, request
`/api/v1/fiqh/search?q=&depth=2&has_children=false&limit=20` and
`/fiqh?basic=1&q=&depth=2&has_children=false&limit=20`. Both return 200;
API returns IDs `[]`, SSR returns roots `[1,2]`. SSR silently ignores visible
filters. `test_regressions.py` deliberately fails the equality contract.
No E4 code edited; coordinator must pass this to the E4 owner.

**Browser startup BLOCKED:** launching `/usr/bin/chromium --headless=new ...`
against the isolated live Django service aborts before DevTools with
`The SUID sandbox helper binary was found, but is not configured correctly`.
The earlier direct baseline launch had the same fatal message. No security
settings, permissions, browser sandbox flags or host configuration changed.
No supported alternative browser connector was exposed to this task. No page
interaction, network/console acceptance or screenshot is claimed. JSON stores
the sanitized startup stderr and all nine cases as NOT_RUN. This is a known
environment blocker, not an auto-review denial and not a product defect fix.

**Integration dependencies:** coordinator/E5 wire commands and artifact directory
in isolated PostgreSQL jobs after assembling lane files. E2 supplies selector/
batch hooks for the new multi-batch UI journey. Final assembled-SHA desktop/mobile
browser execution remains pending and must use a supported protected browser.

Windows, PostgreSQL 17, combined matrix/CI, final assembled browser and real-source
checks: NOT_RUN in this lane. No source service/archive was opened or imported.
Independent review/product acceptance/source acceptance: NOT_PERFORMED.
USAGE_NOT_OBSERVED. NOT_DEPLOYED / GATES_HOLD.
