# Wave7 E6 first harness increment — not persisted workflow acceptance

Frozen base: `34355f5173667c6167351cf379ad56957d7f35f3` / PR58.
Lane: `codex/20261017-wave7-e6`, separate Cloud worktree
`/workspace/fatwa-wave7-e6`. The Wave6 checkout/head is unchanged. Only new
`tests/acceptance/wave7/**` and `docs/dev/wave7/e6/**` files are owned here.
No shared model, migration, fixture, guard, settings, route or CI edit.

The complete recovered leadership spec is now reconciled; the prior missing-spec
transfer issue is resolved. It does not require restarting/refactoring this work.
Scope stays fixed configuration; reference ordinals belong within each item;
known owned nonempty databases remain reusable without reset. E6 resource
selection adds only a narrower test-lane prefix/opt-in before the sole shared
application guard, and does not duplicate its ownership/write policy.

This increment provides guarded test-resource selection, cross-process storage
probes, actual HTTP asset checks, and a protected-engine catalog baseline.
It does **not** implement E1 intake/replay, E2 review, E3 resolution or E4 views.
The persisted-browser label uses actual producer services and published PR61
selectors; until E5 registers its opt-in GET route/flag it fails closed with an
explicit pending code. There is no fake service, E6 URLconf, HTTP write, mocked
browser, optional passing fallback or zero-test success.

## Exact commands and labels for E5

Use Python 3.13 via uv and the existing pinned PyPI requirements; Node 24 needs
no npm package. Example disposable PG18 resources, unique to E6:

```sh
UV_CACHE_DIR=/tmp/e6-uv uv venv --python /usr/bin/python3.13 .venv
UV_CACHE_DIR=/tmp/e6-uv uv pip install --python .venv/bin/python --no-deps --index-url https://pypi.org/simple -r requirements.txt
docker run --detach --rm --name fatwa-wave7-e6-pg18 --publish 127.0.0.1:55476:5432 --env POSTGRES_DB=wave7_synthetic_e6_pg18 --env POSTGRES_USER=wave7_synthetic --env POSTGRES_PASSWORD=e6_disposable_only postgres:18-bookworm
export FATWA_PRODUCTION=0 FATWA_WAVE7_SYNTHETIC_WRITES=1 FATWA_WAVE7_E6_ACCEPTANCE=1
export PGHOST=127.0.0.1 PGPORT=55476 PGUSER=wave7_synthetic PGPASSWORD=e6_disposable_only
export PGDATABASE=wave7_synthetic_e6_pg18 PGTESTDATABASE=test_wave7_synthetic_e6_pg18
.venv/bin/python tests/acceptance/wave7/run.py --suite service --initialize-empty-base
.venv/bin/python tests/acceptance/wave7/run.py --suite service
E6_WAVE7_ARTIFACTS=/tmp/e6-wave7-baseline .venv/bin/python tests/acceptance/wave7/run.py --suite browser-baseline
E6_WAVE7_ARTIFACTS=/tmp/e6-wave7-workflow .venv/bin/python tests/acceptance/wave7/run.py --suite browser
docker stop fatwa-wave7-e6-pg18
```

PG17 was also exercised: `postgres:17-bookworm`, container `fatwa-wave7-e6-pg17`,
port 55477, base `wave7_synthetic_e6_pg17`, test `test_wave7_synthetic_e6_pg17`.
The password above is disposable test configuration, never an owner credential.
Never point these commands at an existing owner/sibling/default database.

The E6 prefix and opt-in are checked before any database lifecycle. E5's actual
`validate_write_configuration`, ownership initializer and `synthetic_atomic`
remain authoritative. Initialization is explicit, only claims an empty database,
and refuses unknown/nonempty/unowned databases. The shared runner verifies the
owned migrated base, refuses a pre-existing TEST database, creates/marks/migrates
only its exact test target and drops only that invocation's created database.
No keepdb, reset, duplicated outer write transaction, grants or security changes.

The existing foundation runner is generic: tested with the exact E6 labels below.
No replacement runner/settings patch is required for the baseline. E5 must wire
these labels explicitly; the existing CI foundation labels do not discover E6.

| Command/label | Expected collection and scope |
| --- | --- |
| `python -m unittest tests.acceptance.wave7.test_target -v` | 4 pure preflight tests; safe for no-DB runner |
| `node --test tests/acceptance/wave7/cdp.test.mjs tests/acceptance/wave7/keyboard.test.mjs` | 8 transport/request-policy/native-key tests; not browser acceptance |
| `python -m unittest tests.acceptance.wave7.test_entrypoints -v` | 1 explicit E1 pure integration regression; PASS on final2678b91 (old c4adc40 failure resolved); missing command still fails on foundation-only lane |
| `run.py --suite service` | `tests.acceptance.wave7.test_storage` (4) + `tests.acceptance.wave7.test_assets` (2), actual PG only |
| `run.py --suite workflow-service` | `tests.acceptance.wave7.test_workflow_services` (2), actual E1/E2/E3 APIs and competing review processes, PostgreSQL only; never browser acceptance |
| `run.py --suite browser-baseline` | `tests.acceptance.wave7.test_browser.BrowserBaselineTests` (1), four actual engine cases |
| `run.py --suite browser` | `tests.acceptance.wave7.test_browser.PersistedWorkflowBrowserTests` (1), eight actual persisted-browser cases; required E5 route/flag and protected engine |

The service and browser commands require the owned PG17/18 setup. Never add their DB labels
to the port-1 pure runner. The runner forces `config.settings.wave7_test`; E5 owns
the later separate opt-in read-only GET integration settings/route registration.

## Real results and limits

- Accepted foundation pure labels: 25 PASS (retained compatibility evidence,
  not new acceptance of unchanged foundation).
- E6 pure preflight: 4 PASS; original Node CDP/policy: 6 PASS, no skips.
  Leadership P2 Enter correction adds two transport regressions: combined Node
  suite now 8 PASS. RED: Enter lacked code/text/unmodifiedText (1 FAIL/1 PASS);
  GREEN: keyDown includes code=Enter and both text fields CR; keyUp includes code
  without a second text injection. Actual native-form browser execution is still
  NOT_RUN while protected engine startup is blocked, not inferred from transport.
- E6 service/storage/live-assets: 6 PASS on PG18.6, 6 PASS on PG17.11.
- RED/GREEN lane-target regression: with shared validation alone, the sibling
  `wave7_synthetic_e5_sibling` target was accepted and the rejection test failed.
  Restoring the E6-only prefix restriction produced all four tests GREEN. The
  negative probe forbids any connection; no sibling database was contacted.
- Browser baseline: one Django gate FAIL because protected Chromium aborts
  before DevTools with the known SUID sandbox error. Four engine cases NOT_RUN,
  zero browser PASS/FAIL/SKIP. Five preflight assets actually returned 200,
  JS/CSS MIME and exact original file bytes. No screenshot fabricated.
- Mandatory persisted workflow: one failing gate; actual services/routes/hooks
  were not integrated at first head2966b99. The owned adapter now implements
  actual E1/E2/E3 preparation and published PR61 UI journeys. Current component
  service evidence and remaining full browser limits are in PRODUCER_HOOKS.md.
  This does not become browser acceptance because service tests passed.

Storage probes parse source only with the approved lossless parser, persist
`SourceSlice.text/start/end` verbatim and inspect them from new Python processes.
They preserve original bytes/hash/question whitespace, invalid/null rows and
UNVERIFIED pointers including `73.000000000000001` / `1e-20000` tokens. The
probe's JSON report contains source **strings**, not decoded/rewritten source
numbers. Rows inserted by the baseline probe remain RECEIVED; no E1 status or
service result is fabricated. Shared catalog fixtures seed outside other units.

Browser baseline uses actual Django `StaticLiveServerTestCase`, original assets
and fixed shared catalog. Native input, detail/history/reload, desktop/390/320
cases and request/console checks require an actual engine. Chromium protections
remain enabled. A supported standard-CI protected Chrome is an E5 integration
need; current Cloud startup failure is reported, never bypassed.

Runtime observed: Python3.13.5, uv0.12.23, Node24.19.0, Chromium154.0.8037.57,
Linux6.18.44 x64. Cloud exec briefly disconnected; a fresh harmless read proved
access restored in the same executor. No duplicate task or alternate host used.
Cloud task URL/ID and quota are not exposed. USAGE_NOT_OBSERVED.

Windows, final combined workflow, real-source acceptance and fresh independent
review: NOT_RUN. NOT_DEPLOYED / GATES_HOLD.
