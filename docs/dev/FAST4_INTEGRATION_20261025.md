# FAST4 integration — synthetic development only

Base/PR target: FAST3 #106, `codex/20261025-fast3-integration-pc2`,
`a149b39bfd624e330762459a7c3e0b4febc7187b`.
Integration branch: `codex/20261025-fast4-integration-pc2`.

Remote PR heads and `git ls-remote` matched the requested SHAs. Each feature
has the exact FAST3 base as its parent; `git cherry` marked each missing before
application. The clean existing integration worktree was used. Applied with `-x`:

| PR | Original commit | Integration commit |
| --- | --- | --- |
| #107 search | b79ffe04e6e93289a9058bf6d8021397ad6df2e0 | 9356f6bd43fdd6b27c2314d49ecd307c38085e18 |
| #108 dashboard | b0272fc88434cd09d3b4c6260ef31c1ea1ee6472 | 28f0d906511f926a5388555f8d2d9794ea5a8862 |
| #109 export | 250274bcd96d18d3f1ed051fd94ec8878ea84e43 | 18706d5f1103968d8c2cbcb4ca0c78b8818b662c |
| #110 follow-up | 8d44932607c5998b60a050e74d6dc5cdaa5e65e2 | 6bd4df3062fbdf03e4f5cc1e98a0bb6762d0e30a |

The three conflicts were additive entries at the start of `config/urls.py`;
all four includes remain, followed by every existing route. FAST2 and FAST3
remain ancestors. No existing feature service was recreated.

Integration adds an Arabic navigation include to all four pages, retaining
their existing FAST3 links, and focusable skip-link targets on search/export.
The new Python integration test first failed for all four missing link sets,
then passed after connection. Browser acceptance lives in `tests/acceptance/fast4`.

Focused verification uses Python 3.13.17 / Django 5.2.18 (external existing
`C:/Users/S.AlAttar/.codex/tmp/fast3-venv/Scripts/python.exe`) and Node 24:

```powershell
$labels = Get-ChildItem tests/editorial_search,tests/editorial_dashboard,tests/editorial_export,tests/editorial_followup,tests/editorial_queue,tests/editorial_workbench,tests/reference_triage,tests/prepared_pipeline -Filter test_*.py -File | Where-Object Name -ne 'test_browser.py' | ForEach-Object { $_.FullName.Substring((Get-Location).Path.Length + 1).Replace('\','.').Replace('.py','') }
python manage.py test @labels tests.integration.test_fast4 --settings=config.settings.test --noinput
node --test tests/integration/ui/catalog.test.mjs tests/acceptance/fastbuild/policy.test.mjs tests/acceptance/wave7/cdp.test.mjs tests/acceptance/wave7/keyboard.test.mjs
python manage.py test tests.acceptance.fastbuild.test_browser tests.editorial_dashboard.test_browser tests.reference_triage.test_browser --settings=config.settings.test --noinput
python manage.py test tests.acceptance.fast4.test_browser --settings=config.settings.test --noinput
python -m apps.editorial_export export --synthetic-fixtures-only --output NEW_DIRECTORY
python -m apps.editorial_export verify --synthetic-fixtures-only --input NEW_DIRECTORY
```

Initial combined run: **251 Python tests PASS**, **57 JavaScript tests PASS**;
real sandboxed Chrome FAST3 **17/17 PASS**, dashboard and reference-triage
browser tests PASS. Django check, scoped Ruff and `git diff --check` PASS.
CLI export/replay PASS. Four output hashes match the existing
[export validation manifest](../../apps/editorial_export/VALIDATION.md), including
report `17d54614349d20488344d2c6d432823d1d8ecb46d34c90f68d129084458725e9`.
That manifest identifies the six fixed synthetic inputs used here; no owner
archives, private records, or production database were used. Local logs reside
in ignored `.local/qa/fast4/`; exact final SHA and Actions results belong in the PR.

FAST4 Chrome 155.0.8059.85 also passed seven grouped checks / 124 requests:
all four pages at 1280/375/320px, native Tab/Enter skip links and cross-page
navigation, all 20 case identities, Arabic CRLF/combining characters, exact
revisions 2/4/7/9/11, filtered follow-up neighbors/reference ordinal/malformed
batch, and all four downloads byte-for-byte against the services and manifest.
No runtime/network/HTTP errors or policy violations. The first version's new
browser HEAD probes encountered `net::ERR_ABORTED` from the bare wsgiref harness
sending HEAD bodies. These checks were moved to a separate Django client test
(all four routes: 200, empty body, no-store), which passed. Browser HEAD transport
acceptance is not claimed; existing browser assertions and strict request policy
were preserved. No application defect was found during this check.

One independent read-only final review examined FAST3 through the four applied
commits plus all integration working changes, including the new browser suite.
No actionable findings. It verified original feature tree equality, route and
guard preservation, revision/reference/export identity links, navigation and
test coverage. It inspected the recorded Chrome report without rerunning tests;
final-SHA CI remained pending at review time. No production approval is implied.

Known upstream CI blocker independently checked: #108 B6 run 40193090623,
job 121168086368 (`wave7-acceptance (17)`) reported `Timed out: DevTools` for
both browser-baseline (4 NOT_RUN) and persisted browser (8 NOT_RUN).
Those results are **BLOCKED**, never PASS. No tests, assertions or browser
startup policies were weakened; no upstream jobs were rerun. Final-head B6/C6/D6
must be checked separately after push, without assuming upstream results apply.

No changes to settings, dependencies, migrations, workflows, catalog assets,
Wave7 transport, AGENTS.md or coordination documents. Rollback is code-only;
no data conversion. No merge or deployment.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED / GATES_HOLD.**
