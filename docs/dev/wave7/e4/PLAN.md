# Wave7 bounded persisted reads implementation plan

> Native execution in the assigned E4 Cloud lane. Parent coordinates independent review and integration. User-authorized ownership overrides generic skill plan-path/approval defaults.

**Goal:** reusable, default-off, bounded synthetic workflow reads for E2 SSR and opt-in GET/HEAD JSON, without changing immutable catalog behavior.
**Architecture:** frozen read DTOs and guarded ORM projections in apps/reference/services.py; shared parameter/context parsing and JSON views in apps/reference/views.py. E2 alone owns workflow templates/UI. E5 alone owns settings/routes wiring.
**Stack:** explicit Python3.13 uv venv, pinned existing dependencies, Node24, owned disposable PG17/18.
**Spec:** root Wave7 dispatch, accepted foundation 34355f5173667c6167351cf379ad56957d7f35f3, approved LOSSLESS_STORAGE.md (acceptance supplied by root supersedes old pending prose). The initially missing leadership-spec field was supplied in full by root during execution; v1.0/continuation/final six clarifications reconciled without changing scope or restarting. Accepted lossless types override early JSON source types.

Constraints: E4 paths only; no shared model/migration/fixture/guard/settings/route edits; no source writes, HTTP writes, permissions/credentials/security changes, main/deploy/Wave8. Exact source bytes/slices and UUIDs remain authoritative; never float-parse source. Read guard precedes any transaction; no write unit on read path. New DB tests use TransactionTestCase and separate explicit labels. Wave6 worktree remains untouched.

## Review focus

- Default flags/app absence, unsafe connection/ownership or old schema: fail closed before workflow queries.
- Same external ID in different batches, malformed/numeric/null source rows and empty refs: stable UUID selection, exact retained text, no invented verified citation.
- Empty/filter-only/all three Arabic modes, wildcards/whitespace, excessive or malformed query params: API and E2 context share semantics and bounds.
- Normalized search without a derived column: exact existing normalization, explicit maximum 1000 candidates/1M question bytes, no silent partial results; select a batch if scope exceeds limits.
- Bounded reference/page materialization, original source numeric spelling/slices, query counts and default-off legacy async tests: no new public behavior or unbounded source decode.

### 1. Guarded read service

Files: apps/reference/services.py; tests/integration/ui/test_wave7_workflow_reads_db.py; tests/integration/api/test_wave7_workflow_reads.py.
- [x] RED: missing entrypoints; default-off/no-ack/invalid params; actual PG persisted batch/item browse, statuses, text/modes, stable UUID selection, empty/blocked rows, exact lossless detail sources and missing refs.
- [x] Implement workflow_batches/workflow_items/workflow_item keyword contracts proposed in Issue50. Use frozen DTOs, fixed scope/config, shared schema/ownership validation without enabling a write tag, bounded scans/projections and explicit sanitized errors.
- [x] GREEN: complete owned no-DB/PG17/18 labels; source fixtures seed using approved parser/synthetic_atomic outside another transaction.

### 2. Shared read query/context and opt-in JSON

Files: apps/reference/views.py; same E4 tests; docs/dev/wave7/e4/INTEGRATION.md.
- [x] RED: query parser unknown/duplicate/excessive/bounds/UUID/status errors, GET/HEAD only, loopback and feature disabled, API/context equality and returned original strings, JSON fail-closed statuses.
- [x] Implement shared workflow_read_context plus three JSON read views; E2 consumes context/service DTOs in its UI. Explicit whitelisted serialization keeps original source tokens as text and does not serialize decoded Decimal source values.
- [x] Supply minimal conditional Wave7-only settings/GET route patch to E5 in documentation; never edit config here. Test-only URLConf lives in E4-owned test module.
- [x] GREEN: no-DB/default-off/API/SSR-context evidence, existing Wave6 Node/API/DB regressions. Actual combined E2 screen/browser remains coordinator/E6 work.

### 3. Evidence and publication

- [x] Record exact commands/counts/query measurements/limits and dependencies; no independent acceptance claim.
- [ ] Commit locally; push/Draft PR targeting codex/20261017-wave7-e5-foundation is held by root pending explicit owner permission after reported E1 publication denial. No alternate publication route. Preserve PR58 metadata and all old heads.
