# Wave3 local and integrated QA

Run `tools\dev\TEST_WAVE3_LOCAL.cmd` from Explorer or any working directory.
Python must be 3.13. The launcher prefers the repository `.venv\Scripts\python.exe`,
then `python` on PATH. Set `FATWA_PYTHON` to a Python executable path when needed
(without surrounding quotes in the value). Install the pinned `requirements.txt`
into that environment beforehand. Node 24 is the existing CI runtime.
The launcher does not install dependencies automatically.

For terminal automation set `FATWA_NO_PAUSE=1`. The launcher returns the dispatcher
exit code, including missing executable failures. Its final JSON reports each suite,
the checked-out SHA, and whether local changes are present. Logs stay on stdout/stderr;
no credentials or database content are collected.

Default checks:

- Discover each of `tests/content_intake`, `tests/fatwa_drafts`, and
  `tests/reference_links` separately using Python's unittest loader. Zero discovered
  tests and import errors fail. Missing/empty package directories report NOT_RUN.
- Run `tests/dev` unittest regressions, Django system checks with the existing
  sanitized test environment, and the existing Node dispatcher.
- Continue after individual failures and return a nonzero exit if any check fails.

Use `--standalone` for only the three Wave3 packages. Use `--require-integrated`
to make missing packages fail the aggregate exit status. Without that flag an isolated
lane can complete available checks while reporting the missing packages as NOT_RUN;
exit zero alone does not mean integrated acceptance.

`.github/workflows/c6-wave3.yml` runs dispatcher regressions and required integrated
packages on Windows and Ubuntu with Python 3.13. Checkout uses the triggering revision
(the merge revision on pull requests); it never checks out a fixed lane branch. Thus
the publisher must combine C1/C2/C3/C6 code before expecting this new job to pass.
The existing B6 Django, PostgreSQL 17/18 and Node jobs remain unchanged.

The local launcher never calls migration, import, Docker or database test commands.
It removes inherited database credentials through the existing QA environment and
sets PostgreSQL to unreachable loopback port 1. PostgreSQL integration continues only
in the existing disposable CI services. No source ZIP or owner database is needed.
No live HTTP checks or browser acceptance are implied by Node tests.

NOT_DEPLOYED / GATES_HOLD. Source acceptance is NOT_RUN. The original 11,397 headings
are reference contents, not fatwas. No publication, approval, media processing,
private workflow or account functionality is activated.

## Wave6 E5 increment

The required pure package list now also includes **all of `tests/fiqh_import`**.
Both Ubuntu and Windows jobs install Node 24, retain Python 3.13, and run the
same fail-closed module inventory. An empty/uncollected module fails alongside
nonempty modules. `--reports .local/qa/c6` saves per-package HEAD, working-tree
state, case totals, module inventory and bounded skip reasons; CI uploads these
as `c6-<os>`. Source-only skips remain explicit, never source acceptance.
See [E5 evidence](../dev/e5/README.md) and its integration dependency handoff.
