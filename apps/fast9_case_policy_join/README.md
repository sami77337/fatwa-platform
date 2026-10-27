# FAST9 case-policy-join — deny-only evidence composition

Development only. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.

Base: FAST8 Draft PR #151, `0769f66e93fdf710ca55e9e68e87430a93f14c40`.
Branch: `codex/20261027-fast9-case-policy-join-pc1`.
PR target: `codex/20261026-fast8-integration-pc1`, never main.

## Gap and implementation

FAST8 `fast8_case_permission` already verifies an exact current queue row and
rechecks it after `policy_gap_engine` evaluation. Its receipt names only a
hypothetical resource; it does not bind actor/action/target or a policy evidence
snapshot. FAST9 composes that service with `permission_lab.build_catalog` and
`policy_gap_engine.evidence.load_evidence`. It does not replace those contracts.

`select_evidence` binds the full exact scenario to one uniquely identified pinned
synthetic evidence record and an exact FAST8 case descriptor. The SHA256 covers
the complete canonical inventory, evidence report and scenario catalog, including
source provenance. Both case and policy identities are checked again after
evaluation. `evaluate_join` requires an independent case/scenario selection,
compares the receipt to fresh sources, calls FAST8's real evaluator, then checks
both identities again. These checks detect observed changes; they are not a
transactional filesystem snapshot, signed capability, or authorization mechanism.

Every diagnostic is `DENY`, `allowed=false`, zero grants, no executable operation.
`synthetic_context=VERIFIED` means only this exact synthetic comparison succeeded.
`owner_policy_connection` and `persisted_case_connection` always remain
`NOT_CONNECTED`. `POLICY_PENDING` and `MISSING_EVIDENCE` are separate fields.
Workflow compatibility probes without a corresponding policy evidence record
return `SCENARIO_EVIDENCE_MISSING` / `NOT_CONNECTED`; no policy connection is inferred
from case status, workflow validity, role hierarchy, or synthetic test success.

Only built-in fabricated cases and the pinned synthetic policy bundle are read.
No custom catalogs, policy paths, user data, source ZIPs, database writes, role
changes, migrations, AI calls, source-owner acceptance, publishing or deployment.
Original Arabic, CRLF, combining characters, timestamps and source bytes are not
normalized or rewritten. Receipts contain comparison metadata, not case text.

## API (coordinator mount required)

App-local `apps.fast9_case_policy_join.urls` provides GET/HEAD `select` and
`evaluate`. Nothing is added to shared settings or URL configuration.
Both require the existing `editorial_demo.views.local_only` guard, nonproduction
settings, loopback Host AND peer, plus `FATWA_FAST9_CASE_POLICY_JOIN=1`.
The actor is a hypothetical catalog label; it is never a session/user role.

Required exact query parameters: `case_key`, `actor`, `action`, `resource`.
Optional: `target_state`. `evaluate` additionally requires `receipt` (the nested
receipt JSON from a successful selection). Duplicate/unknown fields are rejected.
HTTP 200 is a completed synthetic DENY diagnostic, 400 rejected metadata, 503
unavailable/unjoined evidence, 404 disabled/nonlocal, 405 unsafe verb. Responses
are no-store and no-referrer. Shared middleware may reject oversized queries with
its existing `invalid_query` envelope before app dispatch (4096 character limit).
The app separately bounds receipt JSON to 16384 UTF-8 bytes; use CLI stdin for
receipts exceeding the shared URL limit. Neither path accepts public writes.

## CLI

```powershell
python -B -m tools.fast9_case_policy_join --synthetic-only select --case-key batch-synthetic-csv-1 --actor MUFTI --action synthetic::answer.create --resource synthetic::answer
```

To re-evaluate, send only the result's `receipt` object as UTF-8 JSON on stdin:

```powershell
python -B -m tools.fast9_case_policy_join --synthetic-only evaluate --case-key batch-synthetic-csv-1 --actor MUFTI --action synthetic::answer.create --resource synthetic::answer --receipt-stdin
```

Exit 0 means completed synthetic diagnostics, **still DENY**. Exit 3 means rejected
or not connected; exit 2 means invalid arguments/production. Explicit synthetic
opt-in is required. Duplicate flags, malformed UTF-8/JSON, duplicate nested JSON
keys, oversized input, extra grant fields and caller-selected paths are rejected.

## Verification (2026-10-27, Python 3.13.15)

Focused new suite — 29 tests PASS, zero skips/xfails:

```powershell
python -B manage.py test tests.fast9_case_policy_join.test_services tests.fast9_case_policy_join.test_adapters tests.fast9_case_policy_join.test_pg_guard --settings=config.settings.test --noinput --verbosity=1
```

New + affected service/guard regressions — 165 tests PASS, zero skips/xfails:

```powershell
python -B manage.py test tests.fast9_case_policy_join.test_services tests.fast9_case_policy_join.test_adapters tests.fast9_case_policy_join.test_pg_guard tests.fast8_case_permission.test_services tests.fast8_case_permission.test_cli tests.policy_gap_engine.test_evidence tests.policy_gap_engine.test_services tests.policy_gap_engine.test_cli tests.permission_lab.test_sources tests.permission_lab.test_services tests.permission_lab.test_views tests.editorial_queue.test_cross_batch tests.editorial_queue.test_services tests.editorial_queue.test_review_filters tests.editorial_queue.test_views tests.fast8_operator_nav.test_views --settings=config.settings.test --noinput --verbosity=1
python -B manage.py check --settings=config.settings.test
python -m ruff check apps/fast9_case_policy_join tools/fast9_case_policy_join tests/fast9_case_policy_join
python -m ruff format --check apps/fast9_case_policy_join tools/fast9_case_policy_join tests/fast9_case_policy_join
git diff --check
```

Negative cases include cross-case/full-scenario substitution, stale receipts,
row and policy changes after evaluation, missing sources, duplicate external IDs,
duplicate policy/catalog IDs, Unicode lookalikes/hidden characters, unrecognized
actors/resources/actions, internal principal, peer-admin scholarly probe,
resource mismatch, workflow without evidence, parser attacks, and HTTP/CLI guards.
Fault injection changes only in-memory dependency results; successful paths run
the actual existing queue, validators, FAST8 adapter and policy engine.

Observed failures during development: test-first missing-service/adapter/runner
failures; an HTTP assertion incorrectly expected the app envelope after shared
middleware's size rejection; a test client cached middleware while testing the
standalone boundary. Both HTTP tests were corrected to exercise the actual
boundaries. Package-level `manage.py test tests.fast9_case_policy_join ...`
discovery hit the existing namespace-package `__file__ is None` TypeError before
execution; use the explicit module commands above, as shared CI already does.
No assertions were relaxed, no test was skipped, and no shared file was changed.

Full repository DB/browser suites: NOT_RUN locally. No browser was launched;
Django client tests are not browser acceptance. Original source-owner, catalog,
owner-policy and production acceptance: NOT_RUN / NOT_CONNECTED.
Inherited B6/C6/D6 CI does not explicitly collect these new FAST9 modules;
an inherited green run is NOT new-lane coverage. Exact final SHA and actual CI
conclusions belong in the Draft PR and handoff.

Independent final read-only review: one actual GPT-6 Astra review agent inspected
all three owned folders and their dependency/guard contracts, reported **no
findings**, and independently ran the 29 offline tests successfully with zero
skips. It edited no files and ran no PostgreSQL/browser/network operations.

## Exact synthetic fixture identity

Test case: `batch-synthetic-csv-1`, external ID `SYN-CSV-1`, row ordinal 1.
Source kind: `PARSED_FIELDS_SERIALIZATION` (not an original byte slice).

| Identity | SHA256 |
| --- | --- |
| Queue payload | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` |
| Exact source row | `0598e433692f151215645cb4fac62b86aace9f4fa5572ed905bbb7a6d5d9b434` |
| Full queue row | `2867a233ce224c92fdcdbc83f9e72a78949c567bef964d7763e9a0311d872cd1` |
| Policy inventory | `40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4` |
| Full policy evidence/catalog | `477d07e71101fbf9cc33a3a6ed2da41f0825b6f772d824faf93d334ed072dbe4` |

Policy source commit: `88c411852d1a90e62ec71ab1c9ae2278f72d0c76`.
Record: `synthetic-review` / `synthetic::answer.create`.
Scope: `SYNTHETIC_ID_MEMBERSHIP_ONLY`; no reviewed original content binding.

## Optional PostgreSQL non-mutation check

Local result: **NOT_RUN**, `EXPLICIT_OPT_IN_REQUIRED`. No authorized disposable
database identity was supplied for this session; no DB connection was attempted.
Two offline subprocess tests verify refusal without opt-in and with wrong identity.

```powershell
python -B -m tools.fast9_case_policy_join.postgres_check
```

After an operator has independently preauthorized and prepared the disposable
synthetic cluster, the runnable opt-in command is:

```powershell
python -B -m tools.fast9_case_policy_join.postgres_check --preauthorized-disposable-only
```

It requires these exact existing environment values (does not set them or read
credentials from disk): `FATWA_PRODUCTION=0`, `FATWA_WAVE7_SYNTHETIC_WRITES=1`,
`DJANGO_SETTINGS_MODULE=config.settings.wave7_test`, `PGHOST=127.0.0.1`,
`PGPORT=55439`, `PGUSER=wave7_synthetic`,
`PGDATABASE=wave7_synthetic_fast9_case_policy_join`,
`PGTESTDATABASE=test_wave7_synthetic_fast9_case_policy_join`.
Unsafe connection overrides are refused. The base must already be owned and
prepared by the trusted synthetic infrastructure. The command never initializes
the base, discovers credentials, or provisions anything.

The existing `require_synthetic_write` verifies actual database/role/version,
ownership and guard triggers before the existing `Wave7TestRunner` may create its
fresh test database and apply existing migrations. No new schema/migration exists.
The runner rejects pre-existing test DBs and only cleans up the DB it created.
The optional test runs a read-only transaction and forbids all SQL during domain
composition, then checks persisted row count is unchanged. It proves only
non-mutation, **not persisted-case/policy integration or owner acceptance**.
`pg_acceptance.py` is explicitly opt-in, not an offline discovery skip.
