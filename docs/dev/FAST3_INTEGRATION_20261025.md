# FAST3 integration plan and verification

**Goal:** Continue the existing `codex/20261025-fast3-integration-pc2` branch using PR #101 as the immutable base, integrating only missing work from #102–#105.

**Architecture:** Preserve the Wave3/FAST2 ancestry and existing guarded synthetic services. Apply missing source commits with `cherry-pick -x`; make only necessary integration corrections, retaining fixture bytes and protected assets.

**Tech stack:** Python 3.13, Django 5.2, Node 24, protected Chrome/CDP.

**Spec:** Owner's FAST3 integration instruction in this session; source PRs #101–#105.

## Constraints

- Synthetic data only. No YOLO, billing, permission/configuration changes, deployment, main merge, or official gate changes.
- Existing branch only; one Draft PR targeting `codex/20261024-fast2-integration`.
- No recreation of completed functionality. No owner-source or PostgreSQL acceptance claim without execution.
- Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD; NOT_DEPLOYED / GATES_HOLD.

## Execution checklist

- [x] Verify clean existing linked worktree, current base, PR metadata, Wave3/FAST2 ancestry, and absence of an existing integration PR.
- [x] Fetch #102–#105 and inspect ancestry and `git cherry` patch equivalence before applying anything.
- [x] Run focused Python, JavaScript and protected browser baseline checks.
- [x] Cherry-pick only the four verified missing commits with provenance; inspect any real conflicts.
- [x] Run combined queue/workbench/triage/pipeline/intake/revision regressions and focused browser flows, including keyboard, mobile, packets and malformed recovery.
- [x] Resolve integration failures with observed regression evidence; preserve existing services and protections.
- [ ] Perform one independent final read-only review; address material findings and rerun affected checks.
- [ ] Verify final ancestry/protected-path diff, record actual SHA and fixture identities, push the branch and create one Draft PR to FAST2.

## Review focus

- Cross-batch identities and exact revision links must survive queue → workbench → packet navigation.
- FAST2 browser assumptions must match the expanded FAST3 queue without weakening request policy.
- Reference investigation must retain unresolved/malformed evidence without inferred citations.
- Diagnostic export/check must retain byte provenance and reject altered/incomplete bundles.
- Loopback, GET/HEAD, no-store and disabled private/scholarly operations must remain intact.

## Pre-integration evidence

The existing HEAD and PR #101 head are `e64ebc0d219f975eb7be96042a4e8761b1a0e6e9`. Wave3 commit `11902cb` and FAST2 HEAD are ancestors. No pending work or existing PR was found for this integration branch.

Each source has exactly one commit, with parent and merge-base equal to the FAST2 HEAD. `git merge-base --is-ancestor <source> HEAD` returned 1 and `git cherry HEAD <source>` returned `+` for all four:

| PR | Missing source SHA |
| --- | --- |
| #102 | `7b80573a7410422340414a3f712615341089a460` |
| #103 | `9ec6ea1d4334417b86921adf1d6186702abb0808` |
| #104 | `c681be21728dc64f43313707b8f5dfee73ce271f` |
| #105 | `0b1f2d66e78362f0e5be551b78577952c439b2cc` |

The host initially had Python 3.14 without Django. An isolated Python 3.13.17 environment with the repository's pinned requirements was prepared outside the checkout at `C:/Users/S.AlAttar/.codex/tmp/fast3-venv`; no project requirements or settings changed.

## Integration ledger

| PR | Integration commit |
| --- | --- |
| #102 | `0058d4fb143a8ac0130fc7b1276e9747f3562168` |
| #103 | `4ba340db09f98e4d96a93ca3504ed4fdebe619f5` |
| #104 | `a3d76c5158a5f1a10bebe5d348d6932014db6c8e` |
| #105 | `6fa688e805dde43828c35592045bc0ba30abcc5f` |

All four cherry-picks applied without textual conflicts and retain `-x` provenance. A second `git cherry HEAD origin/pr-N` check reports `-` for every source commit. No completed work was recreated.

Baseline: 85 focused Python tests, 56 JavaScript tests and 14 protected Chrome/CDP cases passed at the unchanged FAST2 base (the plan document was the sole untracked path).

Ruling: retain the existing worktree and execute the owner's specified integration directly; no new feature design or implementation delegation is needed. One independent final reviewer will inspect the completed candidate.

Observed integration defects and corrections:

- FAST2 browser queue expectation was stale (9 versus FAST3's 20 records). Corrected to the existing combined fixture count; no service was rewritten.
- Added a failing request-policy test before permitting the precise reference investigation route shape. The local-only/read-only transport and all its negative checks remain intact.
- The added real-browser packet scenario exposed CRLF normalization in HTML. A failing Python regression independently reproduced missing CR character references and initial-newline protection. Packet presentation now escapes text first, preserves CR as `&#13;`, and nests content in a `<code>` child; canonical JSON and original fixture bytes remain unchanged. Snapshot text receives the same treatment.
- Print packets left nested reference reason/evidence details closed. Failing HTTP assertions reproduced this for original history and three prepared cases; the two existing reference partials now expand only when `print_mode` is true. All 20 cases receive the print-expansion check.
- One early combined browser run timed out on `Page.navigate` while the first Python suite was also running. The same navigation passed on subsequent isolated runs; no timeout or browser security setting was loosened. The print test also waits for the rendered print marker, not merely a changed URL.

## Verification commands and current results

Python 3.13.17 / Django 5.2.18 / Node 24.19.0. Commands below use `python` to denote the isolated 3.13 executable, not the host's default Python 3.14.

```powershell
$labels = Get-ChildItem tests/editorial_queue,tests/editorial_workbench,tests/reference_triage,tests/prepared_pipeline,tests/content_intake,tests/revision_core,tests/reference_links -Filter test_*.py -File | Where-Object Name -ne 'test_browser.py' | ForEach-Object { $_.FullName.Substring((Get-Location).Path.Length + 1).Replace('\','.').Replace('.py','') }
python manage.py test @labels tests.acceptance.fastbuild.test_runner tests.editorial_demo.test_revision_history tests.editorial_demo.test_revision_compare tests.editorial_demo.test_revision_adversarial tests.editorial_demo.test_comparison_accessibility tests.editorial_demo.test_history_usability --settings=config.settings.test --noinput
node --test tests/integration/ui/catalog.test.mjs tests/acceptance/fastbuild/policy.test.mjs tests/acceptance/wave7/cdp.test.mjs tests/acceptance/wave7/keyboard.test.mjs
python tests/acceptance/fastbuild/run.py
python manage.py test tests.reference_triage.test_browser --settings=config.settings.test --noinput
python manage.py check --settings=config.settings.development
git diff --check
```

- 465 focused Python tests pass, zero failures/skips; database access is forbidden by the Django view/service tests.
- 57 JavaScript tests pass; new browser module syntax check passes.
- Combined protected Chrome/CDP: 17/17 cases pass after corrections, including keyboard, 320/375px, queue→revision→packet, reference investigation→same prepared record, deterministic JSON digest, exact Arabic/CRLF and complete print expansion. Final committed-SHA run and independent review are recorded below when completed.
- Dedicated reference investigation browser test passes (desktop, 360px, exact Arabic/CRLF, navigation and failed batch).
- Scoped Ruff check passes; formatting checks pass (48 existing/new Python files checked before the presentation correction; all edited Python files rechecked afterward). Django development check and Git whitespace check pass.
- Optional PostgreSQL catalog browser: 5 NOT_RUN, `E6_ACCEPTANCE_OPT_IN_REQUIRED`, zero requests. No PostgreSQL, persisted workflow or owner ZIP acceptance is claimed.

## Synthetic inputs and offline reconciliation

Existing fixture identities remain unchanged: Wave7 payload `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb`; serialized history intake `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0` (serialization, not owner bytes); CSV `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8`; JSON `d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec`; JSONL `e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363`; malformed `d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086` (still zero records).

Ran the documented `diagnose` report/preview/`--show-row a 2`/export/check commands using the two committed new synthetic fixtures. Each returns expected blocked-input exit 1, with no command error: 4 rows, 3 blocked rows, 1 receipt, 1 cross-batch duplicate group, 1 missing source. The new ignored `.local/fast3-diagnostic-20261025` directory contains the verified bundle; sources were not overwritten.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `synthetic-batch-a.csv` | 381 | `123c6f5449df6450baa780bec12e9d7d93d02c277700940ded9ee2df6e1875d4` |
| `synthetic-batch-b.jsonl` | 396 | `584facf57bde2ab1f94ee49ef57ff1f1155d5e5beac0a91f124d12338cd98e63` |
| `diagnostics.json` | 9552 | `e71a375b40e3778a9eeec8ca77f1b301fbcf3f237209aba99747509c8a9fc445` |
| `manifest.json` | 390 | `71f2b6f255880daef251eff0aca3e0058a6c562d47225a64e5a2950e1d569786` |
| `recovery.txt` | 2799 | `62e45df9c0372e95eeead7ef030f40753c72650dd5a08dab8a1f334d95ebc667` |
| `rows.jsonl` | 6771 | `7fc57835ab24916b744c88065f70bb11b6c45ea758af40f4f0901abd40ae12ae` |

The diff against FAST2 is empty for `AGENTS.md`, coordination records, settings, catalog implementation/tests/assets, Wave7 browser transport, workflows, dependencies and intake workflow. Shared `config/urls.py` changes by exactly the reference-triage include from #103. No migrations. Rollback is code-only by reverting this integration branch's commits; no data conversion is required.
