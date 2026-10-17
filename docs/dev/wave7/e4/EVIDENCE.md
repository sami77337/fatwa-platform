# Wave7 E4 local verified increment

Base: `34355f5173667c6167351cf379ad56957d7f35f3`.
Branch: `codex/20261017-wave7-e4`.
Worktree: `/workspace/fatwa-wave7-e4`; original Wave6 worktree remains on `cdbe818e464d1b27d821f620b749c9e526524f19` without edits. Exact local final commit belongs in the final handoff (no self-referential hash in this file).

## Status and authority

Implemented/tested locally. **Publication held by root instruction** after E1 Draft PR creation was denied pending explicit owner permission. This lane has not attempted its Draft PR creation, pushed its branch, created a replacement PR or used an alternate publication route. Root owns the already pending approval request. Target, once approved: ONE Draft PR to `codex/20261017-wave7-e5-foundation`, never main. PR58 metadata is untouched.

Existing selected Cloud executor was reused because fresh task creation is unavailable; no local desktop/DO substitute. Environment ID remains `ccarenv_b64_Y2NhcmVudl81MjI1MTE2ZDg4MjQ4MTkxYjU4OGZkMDYyYTJiYTIzZQ`; actual task URL/ID not exposed, no new cloud task claimed, no subagents launched, quota/usage NOT_OBSERVED. Git fetch of the accepted foundation succeeded, exact SHA and branch absence checked before worktree creation. New remote branch/PR remain unpublished; no publish approval decision invented.

The detailed full leadership specification arrived after the initial literal `undefined` field. Reconciled v1.0, continuation and final six clarifications with the supplied accepted lossless storage contract and implemented work: no storage/identity/status/write-guard conflict or scope change. Original GET UI stays E2-owned; new GET routes/settings remain an E5-only patch.

## Delivered code and integration boundaries

- `apps/reference/services.py`: immutable Workflow read DTOs and default-off guarded batch/item browse/search/detail. Fixed model scope/config, UUID identity, 3 Arabic modes, explicit bounds, exact persisted question, blocked/null/duplicate rows, SourceSlice provenance and no source float reparse. Missing/UNVERIFIED/MISMATCHED refs return no citation; READY_FOR_EDITOR never implies verified evidence.
- `apps/reference/views.py`: 3 GET/HEAD-only JSON exports and shared E2 data/return context, strict query validation, loopback host+peer, redacted JSON errors. Legacy API/view functions unchanged.
- `tests/integration/api/test_wave7_workflow_reads.py`: no-DB/default-off tests and TEST-ONLY URLConf.
- `tests/integration/ui/wave7_workflow_reads_db.py`: explicit PG-only TransactionTestCase label, outside legacy filename discovery so default settings never import workflow models.
- `docs/dev/wave7/e4/{PLAN,INTEGRATION,EVIDENCE}.md`: plan, exact signatures/DTO fields, boundaries and minimal E5-only integration patch.

No catalog.js change: prior keyboard/history/cancellation fixes remain byte-identical to the accepted foundation and are tested. No root/shared/model/migration/fixture/guard/settings/route/CI or other-lane edits. No HTTP writes or owner/source-catalog mutation, real archive use, media fetch or browser security changes. Only approved fixed synthetic catalog fixtures are seeded in owned test databases.

Root supplied actual E2 `load_review_worklist(...)`, persisted GET path and flag after E4 implementation. `INTEGRATION.md` gives the exact page/page_size/q/status-to-E4 adapter and flags. Root/E2 must integrate that E2-owned adapter to avoid independent text semantics; E4 adds no second UI. E6 PR59 handoff was read. Its actual native selectors/event history remain E2 owned, no stub acceptance claimed.

## RED observations

1. Missing public callable contract: 1 test / 1 assertion failure (`workflow_items` absent).
2. First actual PG17/18 read suite: 8 methods / 6 passed / 2 errors due missing JSON view functions, before implementing those views; not a PG pass claim.
3. Summary source projection: 1 method / 2 failing subtests — item summary unnecessarily selected original_row, batch summary selected full original_payload. Fixed using explicit deferred projections, without schema change.
4. Isolated no-DB runner: 49 methods / 4 failures because its ALLOWED_HOSTS contains testserver only while loopback tests use 127.0.0.1. Fixed test-class hosts only; no runner/public settings/security change.

All these failures were inspected; no test weakened/deleted or optional PASS path added.

## Actual commands and results

Runtime: `/usr/bin/python3.13` 3.13.5 via uv venv `/workspace/w7-e4-venv`; Node24.19.0. Existing pinned requirements installed with `uv pip install --python /workspace/w7-e4-venv/bin/python --index-url https://pypi.org/simple --no-deps -r requirements.txt`; uv cache only `/tmp/w7-e4-uv`. No dependency changes/new provider credentials.

Python commands below mean that explicit Python3.13 venv. Counts are per invocation and overlap; do not add them as independent coverage.

| Command | Actual result |
| --- | --- |
| `python manage.py test tests.integration.api.test_wave7_workflow_reads --noinput --settings=config.settings.test` | 8 pass / 0 fail / 0 skip; default-off/no DB |
| `python manage.py test tests/integration/api tests.integration.ui.test_templates tests.integration.ui.test_discovery --noinput --settings=config.settings.test` | 55 pass / 0 fail / 0 skip; includes new 8 |
| `python -B tests/integration/api/run_isolated.py` | 49 pass / 0 fail / 0 skip; connection creation forbidden by runner |
| `node --test tests/integration/ui/adapter.test.mjs tests/integration/ui/catalog.test.mjs tests/integration/ui/tree.test.mjs tests/integration/django-api.test.mjs` | 62 pass / 0 fail / 0 skip; existing Node/DOM/adapter suite, not browser |
| `python -m unittest tests.wave7_foundation.test_contracts tests.wave7_foundation.test_guard_config tests.wave7_foundation.test_lossless -v` | 25 pass / 0 fail / 0 skip; unchanged foundation pure regression |
| `python manage.py test tests.integration.ui.wave7_workflow_reads_db --noinput --settings=config.settings.wave7_test --verbosity=2` | 10 pass / 0 fail / 0 skip on PG17 and PG18 separately |
| `python manage.py test tests/integration/api tests/integration/ui tests.integration.ui.wave7_workflow_reads_db --noinput --settings=config.settings.wave7_test --verbosity=2` | 68 pass / 0 fail / 0 skip on each PG17/18; includes 10 new + legacy E4 API/UI/source-fixture tests |
| `python tools/dev/qa.py system` and `git diff --check` | PASS |

All new PG tests use TransactionTestCase; fixture persistence uses the existing single `synthetic_atomic()` after approved parsing. Fixed synthetic reference seeding is called outside that unit. Read paths issue only SELECT/DECLARE/FETCH/CLOSE, never set a write permit, initialize a DB or open an outer transaction. Tests reopen the DB connection and preserve stored UUIDs/questions/source byte ranges. Large numeric tokens `73.000000000000001`, `1e-20000`, extreme exponents, null/malformed reference values remain exact source text; no float arithmetic or casts.

## Isolated PostgreSQL resources and measurements

Created only these containers: `wave7-e4-pg18` (loopback55574, base `wave7_synthetic_e4_pg18`) and `wave7-e4-pg17` (loopback55577, base `wave7_synthetic_e4_pg17`). Role exactly `wave7_synthetic`; test names exactly `test_` + base. Explicit env: `FATWA_WAVE7_SYNTHETIC_WRITES=1`, `FATWA_WAVE7_SYNTHETIC_READS=1`, `FATWA_PRODUCTION=0`, `PGHOST=127.0.0.1`, explicit port/role/base/test. Disposable-only local password, not an owner credential. Inherited connection overrides sanitized for bootstrap.

Each empty base was claimed by `initialize_synthetic_database(synthetic_fixtures_only=True)` before migrate. Actual marker database name/OID and role/version checked by the shared guard. Existing reference migrations plus workflow0001–0004 applied only to these owned DBs. Each suite used the unchanged Wave7TestRunner to create/claim/migrate/drop its own exact test DB; no reuse/keepdb/reset of unknown/nonempty owner DBs. No shared migration edits.

The full 68-case runs measured a batch-scoped persisted search returning <=2 items over 16 retained synthetic workflow rows:

- PG18: literal 8 queries / 10.350ms; normalized 9 queries / 18.572ms.
- PG17: literal 8 queries / 10.901ms; normalized 9 queries / 13.465ms.

Counts include five shared configuration/ownership/schema SELECTs. No N+1 source payload retrieval in list projections. Exact/literal use ORM predicates; normalized uses the exact existing Python normalization with explicit 1000-row/1M-question-byte work limit and fail-closed `search_scope_required`. These small fixture measurements are not source/production performance acceptance. No global mutable cache or approximate SQL normalization.

Sanitized logs retained in this executor: `/tmp/w7-e4-*.log`.

## Remaining work and held gates

- E5 applies the documented opt-in settings/GET-only route patch and registers the actual E4 labels once: no-DB `tests.integration.api.test_wave7_workflow_reads`; PG-only `tests.integration.ui.wave7_workflow_reads_db`, never port-1.
- E2 owns the single persisted screen, service adapter, native controls/events and route order. E4 context already preserves exact filter/limit/offset return state; E2 maps its page/page_size contract.
- E6 final persisted browser journey and E1/E2/E3 actual service assembly remain NOT_RUN here. No browser/source/whole-Wave7 acceptance or independent review claimed.
- Publication/CI: pending root's explicit owner approval hold; no new Draft PR, branch push, CI success or authorization inferred. Do not modify PR58 metadata.
- Windows, full combined matrix, real-source acceptance/performance: NOT_RUN. MAIN_UNCHANGED/NOT_DEPLOYED/GATES_HOLD; usage NOT_OBSERVED.
