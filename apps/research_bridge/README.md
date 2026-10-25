# FAST5 guarded research bridge

Base: FAST4 `262fa3d40975cfc0698b045becc2da885760a995`.

Implementation plan (user-requested immediate execution):

- [x] Test and implement `services.bridge_reference(ReferenceTriage, catalog=None)`.
  Reuse FAST4 investigation, resolver and Django catalog adapter. Require upstream
  technical verification, all five source pins, exact numeric edition/row and
  unchanged heading, hierarchy and printed location. Never discover an edition
  or match text. Missing evidence or any mismatch yields no catalog link.
- [x] In parallel, implement local-only GET/HEAD Arabic SSR index/detail with
  deep links, native keyboard navigation, exact text and technical recovery.
  Only additive shared change: one include in `config/urls.py`.
- [x] Run new and directly affected tests, including browser navigation and
  disposable synthetic PostgreSQL if available. Record actual limitations.
- [x] One independent final review: no findings; reviewer independently reran
  all 21 service/HTTP tests successfully. Delivery target is one Draft PR from
  the isolated branch to `codex/20261025-fast4-integration-pc2`.

Safety review focus: partial/legacy pins, ambiguous IDs, upstream unverified
references, stale hierarchy/text, unavailable database, query identity overrides,
remote/production requests and non-GET methods. Tests must fail closed for each.

## Use and verification limits

Run the existing development server with its existing PostgreSQL configuration,
then open `http://127.0.0.1:8000/dev/research-bridge`. A stable occurrence URL is
`/dev/research-bridge/intake-1#reference-1`. Native links connect the same case to
the existing investigation and workbench; verified catalog links explicitly carry
both the source row and edition, e.g. `/fiqh/nodes/1?edition=7001`.

The index reuses the 20 fixed FAST4 investigation cases without catalog access.
Details query only references that already have a complete verified identity and
evidence. The authoritative identity is the explicit numeric edition/row plus
source namespace, book ID, edition key, archive SHA256 and input SHA256. All original
work/heading text, complete parent path and printed part/page must also agree with
the current read-only catalog adapter. No default edition, fuzzy search, alternate
mapping or fallback snapshot is used at runtime. Legacy optional pins are required
by this bridge even where older services allowed them to be absent.

Without matching catalog evidence the result shows a reason and Arabic technical
recovery, with neither catalog metadata nor a catalog link. Query parameters cannot
supply or override an identity. No app registration, schema migration or seed is
needed. The existing catalog remains unchanged. This feature deliberately does not
seed Wave7 evidence into the local database just to produce a successful match.

## Synthetic inputs

Existing fixture identities from `build_investigation()` at the FAST4 base above:

| Fixture | Input SHA256 |
| --- | --- |
| revision-history | `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0` |
| wave7 | `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb` |
| synthetic-csv | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` |
| synthetic-json | `d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec` |
| synthetic-jsonl | `e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363` |
| synthetic-malformed | `d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086` |

The `a`/`b` repeated SHA pins in the Wave7 snapshot are fabricated fixture
assertions, never hashes of owner archives. Test snapshots exercise matching and
conflicting evidence; they do not prove that a local PostgreSQL catalog contains it.

## Validation (2026-10-25)

Python 3.13.17, pinned Django 5.2.18 and `requirements-dev.txt` dependencies.
185 new/directly affected tests passed, including real headless Chrome keyboard,
RTL, exact Arabic/CRLF, 320/375px layouts, links and recovery checks. Both the new
research browser test and existing reference-triage browser test passed. Run:

```powershell
$bridgeLabels = @('tests.editorial_workbench.test_services', 'tests.editorial_workbench.test_views', 'tests.integration.test_fast4') + @('tests/research_bridge', 'tests/reference_triage', 'tests/reference_links' | ForEach-Object { Get-ChildItem "$_/test_*.py" | ForEach-Object { $_.FullName.Substring((Get-Location).Path.Length + 1).Replace('\', '.').Replace('.py', '') } })
.venv/Scripts/python.exe manage.py test @bridgeLabels --settings=config.settings.test --noinput
.venv/Scripts/python.exe manage.py check --settings=config.settings.test
.venv/Scripts/python.exe -m ruff check apps/research_bridge tests/research_bridge
.venv/Scripts/python.exe -m ruff format --check apps/research_bridge tests/research_bridge
.venv/Scripts/python.exe -m pip check
git diff --check
```

All listed checks passed. Use explicit test module names as above: initial package
label discovery failed because this repository's `tests`/`reference_links` are
namespace packages (unittest received `__file__ = None`). The corrected command
ran all 185 selected tests. Initial service RED tests observed absent matching and
unavailable-catalog behavior before implementation; initial UI RED returned 404.

**Actual blocker:** Docker's local Linux engine pipe was absent; the default
PostgreSQL listener was unreachable. A real call through `DjangoCatalog` returned
`unverified / catalog_unavailable` with no link or evidence, as intended. Successful
PostgreSQL-backed matching/query counts and clicking through to a populated live
catalog are **NOT_RUN**, not passed. Browser matching uses an explicit fabricated
snapshot and validates the edition-scoped href. No database was created, seeded,
migrated or modified, and no owner ZIP was accessed or claimed validated.

Only built-in fabricated investigation records are accepted. No input uploads,
source import, persistence, permissions, scholarly approval or publication.
Technical matches do not establish scholarly relevance or inspect owner archives.

Gate B NOT_PASSED · C/D/E HOLD · Phase01 BLOCKED · SCOPE_DEVIATION_HOLD · NOT_DEPLOYED.
