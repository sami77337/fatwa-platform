# E5 first-increment verification and publication state

Base: `b5de539237de0cd12b91b0705a3cb92014bfe98b`.
These initial command results were obtained on the E5 working tree before its
first commit; final clean-HEAD reruns are recorded in the producer's final
handoff with the exact final SHA. No claim of independent review is made.

Environment: selected Cloud environment READY; Debian GNU/Linux 13.6 x86_64;
`/usr/bin/python3.13` 3.13.5, Node v24.19.0, uv 0.12.23, Docker 28.4.0.
The environment API exposes no independent publication flag/name or task URL/ID.
Parent source thread: `01a1173c-6c30-723a-828d-8948d842003d`.
Only E5 concurrency was observable here. USAGE_NOT_OBSERVED.

## Actual executions

Commands are from README unless a different invocation is shown.

| Execution | Cases / outcome |
| --- | --- |
| Baseline direct full importer | 82 collected: 78 pass, 0 fail/error, 4 source skips |
| Fixture regression before attributes | 2 methods: 1 failure (CRLF golden SHA), 1 pass |
| Fixture regression after attributes | 2 pass; four disposable LF/CRLF/BOM variants exercised |
| New collection regressions before implementation | 6 methods: 5 failures, 1 pass (expected RED) |
| Django zero-case guard before repair | exit 0 / Ran 0 accepted by old execute; expected assertion failure |
| New collection + Django-count regressions after implementation | 7 pass |
| Full importer after changes | 84 collected: 80 pass, 0 fail/error, 4 source skips |
| Full tests/dev after changes | 49 collected: 47 pass, 0 fail/error, 2 Windows CMD skips |
| qa.py system | PASS, no Django system issues, no DB access |
| qa.py node | 94 registered: 85 pass, 0 fail, 9 skips |
| C6 required pure packages | 11 intake + 17 drafts + 37 reference + 84 importer, 4 source skips |
| D6 --wave3 | PASS: D1 28, D2 16+9+19, D3 37, D4 Django 4 + Node 26, D5 18; nested C6 as above |
| Synthetic B6 PG18 via existing qa_worker | 135 pass, 0 fail/error/skip; actual check, dry migration check, migrate, migrate --check executed |
| Synthetic B6 PG17 via existing qa_worker | process exit 0, Found 135; original stdout-only harness omitted unittest stderr, so detailed counts require final rerun |
| E2 integration-only patch | git apply --check PASS; actual E2 tests NOT_RUN in E5 |
| Windows + Ubuntu hosted matrix | NOT_RUN: remote publication/CI pending |
| E3 real adapter and E6 browser labels | NOT_RUN: actual files not assembled |
| Real source acceptance | NOT_RUN: no trusted owner ZIP/source used |

Counts overlap. They are not distinct-project totals. Node's nine skips are the
missing source archive (one) and Windows-only CMD/PowerShell checks (eight).
The two Python dispatcher skips are Windows CMD execution cases.

## Environment/setup failures, not hidden passes

- Default uv cache was read-only (exit 2); selected `/tmp` cache and installed
  existing exact requirements from PyPI in the uv Python 3.13 venv.
- Initial `qa.py postgres --major 18` was an invalid option (exit 2, no tests).
  Correct existing syntax is `qa.py postgres --postgres 18`.
- Unadapted Docker build could not write its default CLI cache. A task-only
  `/tmp` Docker config resolved that without security-setting changes.
- The runtime image could not resolve PyPI; an environment-only build adaptation
  copied already-installed pinned venv packages into the same Python 3.13 image.
- This environment's bind-mounted checkout was unreadable from the worker.
  The adaptation copied the same synthetic test/code files into the read-only
  worker image. No chmod, security relaxation, owner resources or live DB were
  used. Existing qa.postgres/qa_worker orchestration retained unique internal
  network, tmpfs disposable PG17/18 storage, version/empty-cluster checks,
  read-only worker, cap-drop, no-new-privileges and cleanup. Actual invocation:
  `PYTHONPATH=/workspace/fatwa-platform .venv/bin/python /tmp/fatwa-e5-pg.py 18`
  (also `17`). The temporary evidence adaptation script/logs are preserved for
  the coordinator, not installed as a new project runner.
- One intermediate tests/dev run failed the synthetic dispatcher fixture because
  the new collection reporter initially imported qa.py, absent in the copied
  synthetic checkout. The reporter now records Git identity without that new
  project dependency. All 49 cases subsequently passed/skipped as above.

## Publication observation and recovery

Git fetch and authorized push dry-run initially succeeded. Later remote Git
read failed: `fatal: could not read Username for 'https://github.com': No such
device or address`. Read-only `gh auth status` confirmed the existing `GH_TOKEN`
is invalid. No new credentials, token grant, authentication changes or security
settings were requested or applied. The actual authorized branch push then succeeded via the already configured Git
transport, without any credential change. Git CLI push and the connected GitHub
PR tool published Draft PR56 against the required development base. Thus invalid
gh status was not proof that the existing Git transport lacked push access.
First published/tested clean head: `a82aba4322ff02115b9c1c6fdf57b7c7b80d0a07`.
PR: https://github.com/sami77337/fatwa-platform/pull/56 . No publication blocker
remains. The final handoff identifies subsequent evidence/patch commits exactly.

BOOTSTRAP_STATUS handoff:
https://github.com/sami77337/fatwa-platform/issues/50#issuecomment-6226328246

E2 label source: PR51 at `feb70f0fe9d0fe71765044045bc5924aa175f676`.
The integration-only patch does not modify the active D6 manifest in this lane.
E1/E3/E6 combined execution, fresh independent review and source/owner acceptance
remain pending. NOT_DEPLOYED / GATES_HOLD.


Actual E3 `26dba43149129e3f0cbd5689247cc3da9fe5d3c2` and E6
`fa2b123e967e0550e4c2570d6770e8577aa16e95` files were subsequently fetched and
read without merging. Their integration-only patch is documented in the handoff.
A standard protected Ubuntu Chrome invocation is prepared; combined execution
and browser interaction remain NOT_RUN until assembly/CI. No protection bypass.

Integration patch validation used a separate temporary Python 3.13 uv venv with
PyYAML==6.0.3 from PyPI (no shared dependency changes). Both patches applied in a
disposable copy; JSON D2 label, APP_TESTS AST label, B6/C6/D6 YAML, shell syntax
and embedded Python compilation passed. This is static/configuration evidence,
not cross-lane test execution. Validator and temporary Cloud-PG adaptation are
retained with the final artifact pack for reproducibility.

## Observed hosted matrix for published code

GitHub logs were independently read by this producer (not independent review):
branch head `7b8ec66dde9a55d8fa518cb03af602b1a79dbaa1`, actual PR merge checkout
`4f093ec2f4071461e0693b8bb12ad7ceeea18926`, working tree CLEAN. All three
workflow runs completed successfully; these are lane CI, **not assembled E1–E6**.

- [B6 run 38980007343](https://github.com/sami77337/fatwa-platform/actions/runs/38980007343): PG18 job 117238389415 and PG17 job 117238389729 each ran **135 tests, OK**, zero skips. Real version check and four migration/system steps passed. The two other B6 jobs (system/Node tooling) also succeeded.
- [C6 run 38980007334](https://github.com/sami77337/fatwa-platform/actions/runs/38980007334): Ubuntu job 117238389560 ran dispatcher **49/47 pass/2 Windows skips**, then intake **11**, drafts **17**, links **37**, importer **84/80 pass/4 source skips**. Windows job 117238389933 ran dispatcher **49/49 pass**, then the same pure/importer counts. Both uploaded artifacts successfully.
- [D6 run 38980007403](https://github.com/sami77337/fatwa-platform/actions/runs/38980007403): Ubuntu job 117238389936 and Windows job 117238390256 both passed functional acceptance and uploaded artifacts. Dispatcher counts are **49/47+2 skips** on Ubuntu and **49/49** on Windows. D6's actual summary retains the existing suite counts and nested importer evidence.

Earlier first-head CI also passed at `a82aba4322ff02115b9c1c6fdf57b7c7b80d0a07`
(PR merge checkout `fe663ff3b00ea5b8b74212cc7b713876d9f58efb`). Its run IDs were
B6 38979765623, C6 38979765630, D6 38979765618. These are historical head-specific
results, not a claim about a later commit until its fresh checks complete.

Actual final local PG17 and PG18 reruns at clean `7b8ec66...` each printed
**Ran 135 tests / OK**, zero skips. Both used the documented temporary
Cloud-only package/code-copy adaptation and removed their unique resources.
The final handoff records subsequent documentation/E4-label patch commit and
its actual fresh CI state. E4's actual no-DB label was verified after PR55
publication and is now supplied as a third integration-only patch; E4 DB tests
remain confined to B6 discovery.


## Precise review follow-up: corrected producer modules

This follow-up changes integration-only patches and their documentation. It
reuses the existing environment/dependencies and does not rerun old producer
work, importer suites or browser execution. Previous green CI remains evidence
only for its recorded SHA until the new E5 head's automatic checks complete.

Read actual E2 `b1289215a8cc83a20a70caed553bf664dea7be40`:
`docs/dev/e2/REVIEW_FIXES.md` and `tests/editorial_demo/test_review_fixes.py`.
The latter declares two SimpleTestCase classes, six test methods. The patch now
requires BOTH `tests.editorial_demo.test_synthetic_batch` and
`tests.editorial_demo.test_review_fixes` in D2, preserving the original three
labels. E2 reports 61 editorial passes; these tests were NOT_RUN by E5.

A targeted configuration check first rejected the old patch because the second
label was absent (AssertionError, exit 1). After the update, sequential checks
of all three patches passed in a disposable copy: exact five-label D2 list,
E4 no-DB label, E3 APP_TESTS/qa_worker syntax, exclusion of real E3 DB labels from
D6, three workflow YAML parses, Bash syntax and embedded Python compilation.
Actual command: `/tmp/fatwa-e5-yaml-venv/bin/python /tmp/fatwa-e5-validate-patches-review.py`.
This is configuration RED/GREEN, not an editorial test result.

Also inspected newly published E6 PR52 head
`a541cd9b3693e034173242f44fdb33dbb7358e2b`: README, actual run.py,
test_browser.py, test_assets.py and test_review_batches.py. Its shared live server
is now static-files-aware. The integration-only workflow patch adds the actual
`--assets` and `--review-batches` gates and invokes `--browser --review-batches`
for the tenth mandatory journey. Each gate retains explicit isolated database
acknowledgement, failure propagation, a nonzero-case check and artifact logging.
Protected Chrome remains required; no security settings or bypass flags change.

E6's new asset/review/browser commands are NOT_RUN in E5; final execution is
coordinator-owned after assembling corrected E1/E2 and actual E3/E4/E6 modules.
E6's README still cites the initial E2 snapshot for its own batch evidence; do
not transfer that result to corrected E2 or the assembled SHA without execution.
No neighboring code merged, shared-root dependency/route edit, source operation,
product/source acceptance or independent re-review is claimed.
`NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED`.
