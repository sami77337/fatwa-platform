# FAST5 integration — synthetic development only

Base and Draft PR target: FAST4 #111,
`codex/20261025-fast4-integration-pc2`,
`262fa3d40975cfc0698b045becc2da885760a995`.
Integration branch: `codex/20261025-fast5-integration-pc2`.

## Execution ledger

1. Verified the existing isolated worktree was clean and HEAD was exactly the
   requested base. GitHub PR metadata, fetched branches and `git ls-remote`
   agreed on all four source heads. Each has the exact FAST4 base as its parent;
   `git cherry` marked all four missing. Applied only these commits with `-x`:

| PR | Original SHA | Applied SHA |
| --- | --- | --- |
| #112 workflow | d087d4b50404d2830fb8a881c13766fa52134a97 | a54f916 |
| #113 transcripts | 22deced84d4ea1ddbffe556cd2300cf45fdcdcf9 | 23958b4 |
| #114 research | d0207cc9e247378fad144766233289d048ca9ab5 | 2e07979 |
| #115 permissions | f736823fdd8f075b22d1c27bbc60777f6a9df311 | 852e157 |

2. Resolved two additive `config/urls.py` conflicts, preserving all three new
   includes and every existing route. No completed service was reimplemented.
3. Added shared Arabic navigation between FAST4 and the three FAST5 screens,
   plus an exact case/occurrence link from rehearsal to the research bridge.
   New integration tests first failed on the eight missing link assertions,
   then passed. Offline transcript processing remains the existing CLI, with
   its question export consumed by the existing synthetic preparation service.
4. Ran the focused combined checks below. The final independent review and
   exact final-SHA CI results are recorded in the Draft PR; source PR results
   are not substituted for integration results.

One independent final read-only review completed with no unresolved actionable
code findings. The reviewer independently passed 78 focused tests and checked
the 60 unchanged Git blobs, five original S3 artifacts and route/guard boundaries.
One low-severity description of the file count was corrected. Real PostgreSQL
matching/performance, owner archives, historical policy acceptance, scholarly
correctness, production readiness, browser HEAD transport and final remote CI
were explicitly outside that review's acceptance claim; these limits stand.

## Connected behavior

- `/dev/workflow-rehearsal`: intake/preparation, accepted and rejected review
  attempts, immutable revisions/audit and workbench/reference links. Internal
  completion is explicitly not scholarly approval.
- `python -m tools.transcript_pipeline`: bounded offline CSV/JSON/JSONL parsing,
  manually supplied boundaries, exact Arabic/timestamps and source hashes.
  Prepared export retains questions; original answers remain in the report.
  Existing preparation produces review/unverified statuses and zero drafts.
- `/dev/research-bridge`: exact edition/row and all five source pins, original
  heading, full hierarchy and printed location must agree. Missing evidence or
  unavailable catalog yields no link. No inferred source identities/citations.
- `/dev/permission-lab`: every hypothetical check remains DENY_DEFAULT;
  pending policies remain denied. No real roles, authentication, permission
  store or transition execution is introduced.

## Measured local evidence

Runtime: Python 3.13.17 and pinned Django 5.2.18 in existing external environment
`C:/Users/S.AlAttar/.codex/tmp/fast3-venv/Scripts/python.exe`, Node 24 and sandboxed
Chrome 155.0.8059.85. No dependency or environment configuration was changed.

- Combined Python: **606 discovered, 605 passed, 1 skipped**, 51.655 seconds.
  The skip is `ExistingSnapshotReadOnlyTests.test_every_historical_field_matches_and_read_only_rerun_is_identical`:
  `REAL_DB_AUDIT_NOT_RUN: requires trusted ZIP and explicit FATWA_622_AUDIT_EDITION`.
  This is not owner archive or database acceptance.
- JavaScript: **57 passed**, zero failures/skips, for directly relevant catalog,
  request policy, CDP and native keyboard behavior.
- Actual transcript CLI report/prepared exports passed; their SHA256 values are
  `d252494ffc92bd35838ce539848e8ad2441e63c699399b18d5fdfa995f8552e2` and
  `9c3e678856c05ff7c00bdcfddc9e7c55f72075f8e0c3bd276f2ddc8194580385`.
  Feeding the prepared bytes into `prepare_batch` produced zero drafts and
  `needs-editor-review / references-unverified`.
- Browser collection: **6 Python tests passed**, 27.689 seconds: five actual
  Chrome checks (rehearsal, research, permission lab, FAST4 and FAST5), plus the
  existing FAST4 Django HEAD check. FAST5 made **159** guarded local requests;
  rehearsal 114; FAST4 124. Responsive Arabic RTL at 1280/375/320px, native
  keyboard links/forms, immutable replay, exact Arabic/CRLF/combining marks,
  source hashes and existing export bytes passed. FAST5 reported zero runtime,
  network, HTTP errors or request-policy violations.
- New Django checks confirm empty/private HEAD responses on all three new
  routes. Browser HEAD transport acceptance is not claimed (existing bare WSGI
  harness limitation remains documented in FAST4).
- Research browser matching uses an explicitly injected fabricated catalog
  snapshot. It verifies hierarchy and edition-scoped hrefs; it does not click
  into a populated PostgreSQL catalog. An actual default `DjangoCatalog` call
  returned `unverified / catalog_unavailable`, with no evidence or URL.
  Successful local PostgreSQL matching/query-count acceptance is **NOT_RUN**.
- Django system check, scoped Ruff lint/format, JS syntax and whitespace checks
  passed. A redundant environment inspection found no `pip` module in the
  existing venv; no dependency installation or `pip check` success is claimed.

Reproduction (substitute the Python 3.13 executable above for `python`):

```powershell
$dirs = 'workflow_rehearsal','transcript_pipeline','research_bridge','permission_lab','editorial_workbench','reference_triage','reference_links','prepared_pipeline','content_intake','fatwa_drafts','revision_core','editorial_search','editorial_dashboard','editorial_followup','editorial_export','editorial_queue'
$labels = $dirs | ForEach-Object { Get-ChildItem "tests/$_" -Filter test_*.py -File } | Where-Object Name -ne 'test_browser.py' | ForEach-Object { $_.FullName.Substring((Get-Location).Path.Length + 1).Replace('\','.').Replace('.py','') }
python manage.py test @labels tests.integration.test_fast4 tests.integration.test_fast5 tests.wave7_foundation.test_contracts tests.reference.test_asset_integrity tests.integration.source.test_existing_snapshot --settings=config.settings.test --noinput
node --test tests/integration/ui/catalog.test.mjs tests/acceptance/fastbuild/policy.test.mjs tests/acceptance/wave7/cdp.test.mjs tests/acceptance/wave7/keyboard.test.mjs
python manage.py test tests.workflow_rehearsal.test_browser tests.research_bridge.test_browser tests.permission_lab.test_browser tests.acceptance.fast4.test_browser tests.acceptance.fast5.test_browser --settings=config.settings.test --noinput
python manage.py check --settings=config.settings.test
```

Local logs and reports are in ignored `.local/qa/fast5/`. Initial results above
used applied HEAD `852e157` plus the integration working changes. Final-SHA
verification is separately recorded in the PR, without attributing these runs
to a commit that did not yet exist.

## Source integrity and unchanged boundaries

All 60 unmodified imported files, excluding `config/urls.py` and the three
templates extended for navigation, match their original source Git blobs
(workflow 13, transcripts 11, research 12, permissions 24). The only existing
FAST4 files changed are `config/urls.py` and the shared navigation template.
All existing services, fixtures, protected source files, assets, settings,
dependencies, migrations and workflows are unchanged. Existing FAST1–FAST4
history remains in ancestry. Template additions preserve existing bytes and
line endings; protected snapshots are not reformatted.

All five vendored S3 artifacts match both manifest SHA256 and original Git
objects at `88c411852d1a90e62ec71ab1c9ae2278f72d0c76` byte-for-byte. They contain
four invented action rows and one transition, not the missing 70 historical
permission rows or 58 transitions.

| Synthetic input | Exact SHA256 |
| --- | --- |
| Transcript `tools/transcript_pipeline/examples/synthetic-manual.json` | e217c93eac5fa0109e3c4134b478ce3e6500e8723692312a6c14194ccece40ee |
| Wave7 `synthetic_payload()` | cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb |
| Serialized history intake | 75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0 |
| S3 synthetic inventory | 40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4 |
| S3 synthetic excerpt | 266e07ae6b229a19df2d11b8a9aa986e9cd468a05ecacfd7d22de3ebdd7b760d |

The other fixed preparation fixtures are identified in
[`apps/research_bridge/README.md`](../../apps/research_bridge/README.md).
Existing FAST4 export hashes remain unchanged, including report
`17d54614349d20488344d2c6d432823d1d8ecb46d34c90f68d129084458725e9`.

No private records, media downloads, AI answers, publication, role grants,
production writes, deployment or merge. No production migration or data
conversion is needed; rollback is code-only. The absent historical policies,
original source acceptance and 76 pending U03/U10 clauses remain blockers to
their respective acceptance scopes, not invented implementation inputs.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED / GATES_HOLD.**
