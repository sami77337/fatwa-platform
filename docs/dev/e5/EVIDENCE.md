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

## Publication blocker

Git fetch and authorized push dry-run initially succeeded. Later remote Git
read failed: `fatal: could not read Username for 'https://github.com': No such
device or address`. Read-only `gh auth status` confirmed the existing `GH_TOKEN`
is invalid. No new credentials, token grant, authentication changes or security
settings were requested or applied. Remote Git publication and Draft PR creation
are blocked pending the coordinator's authorized recovery of existing access.
A local commit, patch/bundle and sanitized evidence are preserved; do not call
this increment PUBLISHED without the actual remote branch and Draft PR.

BOOTSTRAP_STATUS handoff:
https://github.com/sami77337/fatwa-platform/issues/50#issuecomment-6226328246

E2 label source: PR51 at `feb70f0fe9d0fe71765044045bc5924aa175f676`.
The integration-only patch does not modify the active D6 manifest in this lane.
E1/E3/E6 combined execution, fresh independent review and source/owner acceptance
remain pending. NOT_DEPLOYED / GATES_HOLD.
