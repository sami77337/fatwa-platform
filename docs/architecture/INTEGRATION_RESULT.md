# Integration acceptance result — 2026-10-15

NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD. Gate B NOT_PASSED,
C/D/E HOLD, Phase01 BLOCKED. U03/U10 remain OWNER_APPROVAL_PENDING.

## Current accepted catalog

REAL_SOURCE_DATABASE_IMPORT=PASS. DJANGO_SITE_HTTP=PASS.
REAL_CATALOG_HTTP=PASS. The genuine book-622 catalog is operational at
http://127.0.0.1:8000/fiqh. A duplicate import was skipped because the existing
edition was already complete. No database write was performed in this continuation.

Code HEAD: d7b6dc1e4d50b87a88cca036a6025352ecc0ccbe, branch
codex/integration-site-v1-20261015, with preserved uncommitted integration changes.

The original input fixture is
FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip, member
FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl, outside Git.

| Identity | Actual SHA256 |
| --- | --- |
| Original ZIP, rehashed in this continuation | 82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce |
| JSONL member, rehashed in this continuation | 37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14 |
| Independent original-title CSV | 13edc878f0b81d178c104bc976c4fe0d3970d8a1ef8bae26d6101f22ebbcd1a9 |
| Source mapping and independently reconstructed live mapping | b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7 |

## Evidence provenance

The existing Git-ignored .local/host-result.json, timestamp
2026-10-15T11:35:19.996Z, records the completed one-click host workflow:

- PostgreSQL server_version_num=180006, database=fatwa_reference, role=fatwa_app.
- Before: zero headings/roots; checksum-pinned dry-run returned 11,397 records.
- Import action: IMPORTED. After: 11,397 headings, 32 roots, maximum depth 5.
- Read-only post-import preview: unchanged=true, with every original persisted
  field, parent, normalized title and edition compared by the existing S0 importer.
- S1 suite: 59 tests PASS, including real source acceptance for JSONL, CSV and
  nested JSON. Frontend regressions: 30 PASS. Live HTTP probes: PASS.

This continuation did not execute that import again. Its Docker engine pipes and
Python base executable remain access-denied. Direct SQL and Python/S1 results above
are saved host-run evidence, not commands newly executed by this agent.

Current independently executed acceptance uses
[tools/dev/verify-live.mjs](../../tools/dev/verify-live.mjs). It makes bounded
loopback HTTP requests through the existing Django ORM-backed public APIs, writes
only a Git-ignored summary, and preserves the original host report:

- 285 paged catalog requests compared all 11,397 unique live records with the
  checksum-pinned original JSONL and the independent original-title CSV.
- Every exact title, source ID, parent edge, sibling position, source order,
  printed part/page, source page ID and source entry number matched.
- Every node's complete live parent ID/title path matched the original source.
- 32 actual roots, maximum depth 5. Depth counts: 32 / 475 / 10,673 / 215 / 2.
- The complete live mapping reproduced the source checksum above.
- Live edition attribution, depth-five detail, nested/anchored child paging,
  exact/literal/normalized search, SSR and rejected writes passed.
- Current repeatable result: .local/live-verification.json, LIVE_SOURCE_CATALOG=PASS.

## Checks and remaining limits

- This continuation ran 36 Node regression tests: 36 PASS, 0 failures/skips.
  Mock transport and synthetic fixture tests are distinct from the exhaustive
  live real-source check above; they do not establish source persistence on their own.
- Native Ruff check passed for config, apps/reference, tests/reference,
  tests/integration, manage.py, the book622 bridge and container worker.
- JavaScript syntax and git diff whitespace checks passed.
- Live /fiqh, /readyz, SSR and integrated static assets returned 200.
  POST/PUT/PATCH/DELETE returned 405; admin, fatwa and synthetic fixture asset
  routes returned 404. Invalid/duplicate query parameters returned 400.
  Responses retain the restrictive CSP. Current detail: .local/http-security.json.
- Django/PostgreSQL test suite: NOT_RUN. The host runner reported no accessible
  empty dedicated test_fatwa_reference_dev database. None was created or reset.
  This agent could not rerun database tests because Docker/Python access is denied.
- Browser/mobile/keyboard acceptance: NOT_RUN. Fresh Chrome 155 and Edge 155
  reached DevTools but timed out at Page.enable before UI initialization.
  The connected browser tool returned an empty browser inventory.
  No visual, mobile or keyboard pass is inferred from HTTP/HTML availability.
- No new performance benchmark, coverage or production acceptance is claimed.

Changes in this continuation: a repeatable read-only live verifier and corrected
current-state sections of README and this report. Existing code and host runner
were preserved. No commit, push, PR mutation, merge, deployment, volume reset,
credential/network change or sibling-worktree change was made. The existing
one-click [START_LOCAL.cmd](../../tools/dev/START_LOCAL.cmd) remains available
for future host continuation; no owner command sequence is needed.

## Historical baseline evidence

The following records predate the completed host import and are retained as history.
Their old runtime blockers do not override the accepted current catalog above.

## Baselines and scope

- Integration branch: codex/integration-site-v1-20261015.
- Preserved S0 HEAD: d7b6dc1e4d50b87a88cca036a6025352ecc0ccbe.
- Imported S1: 4460cd2fb86054544f57aae051e7ec8ca90ee06a
  (tools/fiqh_import, tests/fiqh_import, docs/data-ingest only).
- Imported S2: a189190ad91bfa33cd897dfadbb7fbb60eb790b6
  (ui_drafts/fiqh and docs/ui-api-contract only).
- Source content was copied by reading Git objects into this integration worktree;
  no checkout, merge, index staging, commit, push or deployment was performed.
- S0 models, immutable PostgreSQL migrations, middleware and settings were retained.
  Existing APIs gained only optional root search scope and child anchor paging.
- S2's functional UI was adapted into Django templates/static modules. It uses
  same-origin real Django endpoints, preserving SSR/no-JavaScript navigation.
- The local launcher reads the existing isolated S5 configuration/credentials,
  never rewrites them, and binds the browser server to 127.0.0.1:8000.

## Historical integration checks — before host import

| Check actually attempted/executed | Result |
| --- | --- |
| node --test tests/integration/django-api.test.mjs plus S2 api/server/source-identity tests, with FATWA_622_ARCHIVE pointing to the actual owner ZIP | PASS: 30 tests, 0 failed, 0 skipped. 11 exercise the new S0 adapter; 19 are inherited S2 regressions/identity checks. HTTP responses in adapter unit tests are explicit test fixtures, not a running Django service. |
| node --check apps/reference/static/reference/catalog.js | PASS |
| node --check apps/reference/static/reference/django-api.mjs | PASS |
| PowerShell Parser.ParseFile on tools/dev/site.ps1 | PASS: syntax only, not a successful launch |
| Standalone native Ruff 0.17.0: check --no-cache config apps/reference tests/reference tests/integration manage.py tools/fiqh_import/book622.py | PASS |
| Native Ruff --select E9,F over explicit S1 Python files | PASS after removing one unused inherited test import |
| Native Ruff format --check over the seven integration-edited Python files | PASS |
| Native Ruff format --check over all S0 config/app/reference tests plus integration | FAIL: 17 inherited S0 files require formatting. Kept unrelated foundation files unchanged; no claim of a full formatting pass. |
| git diff --check | PASS for tracked modifications; separate new-text whitespace scan also performed |
| Python venv --version, manage.py check, makemigrations --check --dry-run, Django tests, S1 unittest discover, Python-invoked Ruff/mypy | NOT_RUN: venv launcher exit 103; its Python313/python.exe base is access-denied. Native Ruff was run separately. |
| docker ps | NOT_RUN: Docker engine named pipe permission denied; user Docker config also access-denied. No config was copied or permissions changed. |
| TCP connection probes 127.0.0.1:5432 / :55432 / :8000 | ECONNREFUSED on all three |
| Source ORM preview/apply/rerun, PostgreSQL migrations/integration, browser keyboard/mobile/no-JS smoke, coverage and performance | NOT_RUN because required runtime/database were unavailable |

The command runtime itself failed before spawning processes (setup refresh errors).
Read-only inspection and permitted workspace edits/checks used the local Node
runtime instead. The installed shared venv exists at
control/venvs/s0-py313 but resolves to an inaccessible base Python executable.
A request to obtain a separate Python runtime from python.org failed due to
unavailable network access. No system installation or sandbox changes were made.

## Historical owner source inspection

Input files remained at inputs/starter/FATWA_CODEX_START_20261013 outside this
worktree. Independent Node ZIP/data inspection executed in this session:

- TOC ZIP SHA256:
  82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce.
- JSONL member: FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl.
- JSONL SHA256:
  37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14.
- Independent original-title CSV SHA256:
  13edc878f0b81d178c104bc976c4fe0d3970d8a1ef8bae26d6101f22ebbcd1a9.
- 11,397 unique IDs; every original ID/title pair matched the independent CSV.
- Exact 32 root IDs matched the pinned edition: 30 fiqh books and 2 introductions;
  maximum depth 5; all 11,397 nodes reachable; parent-first input.
- Depth counts: 1=32, 2=475, 3=10,673, 4=215, 5=2.
- Verified original parent links, depth, source paths, unique sibling positions,
  child counts/leaf flags, title keys and positive printed/page-ID references.
- All 11,397 CSV records and all 11,397 nested JSON nodes matched JSONL fields.
- Sprint ZIP SHA256 also matched:
  2b50ef138d2890156121e784618715e9992e04bed7d437bbf13e5d6250d0e78b.

These are independent source-inspection results. They are not execution of the
S1 Python importer or the new S1-to-S0 bridge, and do not establish PostgreSQL
persistence acceptance. Upstream 622.db and title.zip were not supplied.

