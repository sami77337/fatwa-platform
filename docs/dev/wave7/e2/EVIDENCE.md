# Wave7 E2 execution evidence

Base `34355f5173667c6167351cf379ad56957d7f35f3` on accepted
`codex/20261017-wave7-e5-foundation`. New isolated worktree
`/workspace/fatwa-wave7-e2`, branch `codex/20261017-wave7-e2` (checked absent first).
Old Wave6 worktree remains clean at `b1289215a8cc83a20a70caed553bf664dea7be40`.
The exact published head/CI and Draft PR URL are recorded in the handoff/PR.
No PR58 metadata was changed. No shared model/migration/guard/fixture/settings/
route/CI file is modified. Interfaces and the exact E5 patch proposal are in
[CONTRACT.md](CONTRACT.md).

Cloud execution remained available in the selected existing E2 environment
`ccarenv_b64_Y2NhcmVudl9mYWE2OTJhMjg0MTQ4MTkxODlmNmI4ZTI5NDYyYzMwNA`.
No new Cloud task URL/ID is exposed; one worker observed here, global concurrency,
quota and usage NOT_OBSERVED. Python 3.13.5 `/usr/bin/python3.13`, Node 24.19.0,
uv 0.12.23, Docker 28.4.0. No desktop or alternate host was used.

## Implementation

`transition_review` validates canonical UUIDs, bounded exact UTF-8 reason, action
and expected status before entering the sole shared synthetic_atomic unit. That
unit's guard precedes atomic(). Only the selected item is locked (`of=('self',)`);
operation lookup follows the lock. Exact replay returns the original event, even
if later operations changed current status. Changed action/expected-status/reason
fails closed with REVIEW_CONFLICT; a stale new operation also conflicts. Status
update and append-only event insertion commit or roll back together. All four
frozen legal transitions use the shared transition matrix. No answer, scholarly
approval or publication state exists.

`wave7_review transition` invokes that service without an outer transaction and emits only a
bounded derived UUID/status/replay receipt. Validation/guard/database errors use
fixed codes and do not echo source/reason/connection details. It is absent from
default settings because only the separate Wave7 app registers it.

`load_review_worklist` reads owned fixed-scope batches after the existing ownership
configuration guard. Batch options fetch only ID/date (latest 100 plus an explicitly
selected older batch), not every raw payload. The selected batch parser validates
exact raw SHA and per-item/per-reference text and byte offsets. No default float
JSON decoder rewrites source; null/nonstring IDs are never cast. Separate intake,
reference and review states remain independent. No citation is derived from
readiness. Page size <=50, per-item references <=100, input batch <=1000 rows/1MB.
Detail history is latest 100 with an explicit truncation marker; lists load none.

The new `persisted_review` view is GET/HEAD-only, loopback-only, feature-default-off
and app-registration-gated. A test-owned URLconf proves its exact proposed shared
route without editing shared URLs. Selection uses batch/item UUIDs, preserving
state through detail/return/reload and a fresh Python process. All source/citation/
event text is autoescaped; media is text only. Existing Wave6 execution paths are
unchanged and their complete 61 tests still pass. The public/base settings and
routes do not expose the persisted service; E5 must explicitly wire the proposal.

## Dependency setup and disposable services

```sh
UV_CACHE_DIR=/tmp/fatwa-e2-uv uv venv --python /usr/bin/python3.13 /tmp/fatwa-wave7-e2-venv
UV_CACHE_DIR=/tmp/fatwa-e2-uv uv pip install --python /tmp/fatwa-wave7-e2-venv/bin/python --index-url https://pypi.org/simple --no-deps -r requirements.txt
```

Only the eight existing exact PyPI pins were installed. A temporary Cloud-local
resource helper `/tmp/w7-e2-postgres.py` launched exactly its own containers,
recorded IDs/ownership labels in `/tmp/w7-e2-pg17.json` and `...pg18.json`, and
verified those identities before every command/cleanup. Official images:

- postgres:17-bookworm, digest `sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826`, actual server 170011.
- postgres:18-bookworm, digest `sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c`, actual server 180006.

Random host ports were bound only to literal 127.0.0.1, data in tmpfs, role exactly
wave7_synthetic; base/test names were unique wave7_synthetic_e2_17_* / 18_* and
matching test_ names. Fixed synthetic-only flags, no inherited PG/credential
connection overrides. Empty database initialization and actual 0001–0004 migration
used the unchanged ownership guard; each test run used the unchanged Wave7 runner,
which created/marked/dropped only its own test DB. No owner catalog/data was used.
No security/sandbox bypass or role/server-policy changes were made.

## RED and corrected setup

Baseline pure foundation contracts/guards/lossless: 25 methods passed, 0 skipped.
Owned review DB label first failed import because review service did not exist.
New default-off tests first had two missing-view errors; the initial route test
also assumed Resolver404, corrected after observing the old generic preview route
catches `persisted` as an unknown external ID. It now verifies the actual boundary:
no Wave7 named route/CLI registered, direct feature-off view 404 before queries.
New read DB module ran 10 methods with 9 missing-view/import errors before the
adapter existed. The first rollback-injection test patched Manager.create, while
using() creates through QuerySet; correcting the injection site produced the
actual rollback proof. These are disclosed test setup corrections, not hidden
production failures. Subsequent full tests pass without removing negative cases.

## Actual verification commands

`/usr/bin/python3.13 /tmp/w7-e2-postgres.py run <17|18> ...` executes its arguments
with `/tmp/fatwa-wave7-e2-venv/bin/python` inside this checkout and only its verified
owned synthetic target. Before migrate it invoked:

```python
import django; django.setup()
from apps.intake_workflow.guards import initialize_synthetic_database
initialize_synthetic_database(synthetic_fixtures_only=True)
```

Commands on both targets:

```sh
manage.py migrate --noinput --settings=config.settings.wave7_test
manage.py check --database default --settings=config.settings.wave7_test
manage.py test tests.wave7_foundation.test_database tests.wave7_foundation.test_review_regressions tests.wave7_foundation.test_lossless_db tests.editorial_demo.test_wave7_review_db tests.editorial_demo.test_wave7_read_db --noinput --settings=config.settings.wave7_test
```

First committed checkpoint `6ef2e705058752de154e612c31b6b673462cd685`:
**61 methods on PG17 and 61 on PG18**, 0 failed/errors/skips
(34 unchanged foundation + E2 review 15 + E2 persisted read 12). The 12th read
method launches a fresh Python process against the owned test DB, verifies the
committed review status, and compares exact original source bytes. Earlier full
runs before that method had 60 methods; these counts overlap, do not sum them.
Initial lane-only runs: 27/27 on each PG major. After the full-spec CLI correction
below, lane-only runs are **28/28 on each PG major** (review 16 + read 12).
Fresh committed-head full counts are published with the PR; those supersede the
first checkpoint, rather than counting reruns as independent coverage.

PG17 `makemigrations --check --dry-run`: no changes; PG18 `migrate --check`: PASS.
Django system checks on both actual targets: zero issues. Only new services,
command, owned view/template/tests/docs change; no parallel migrations.

No-DB commands (ordinary default settings, PGPORT=1):

```sh
/tmp/fatwa-wave7-e2-venv/bin/python -m unittest tests.wave7_foundation.test_contracts tests.wave7_foundation.test_guard_config tests.wave7_foundation.test_lossless -v
PGPORT=1 /tmp/fatwa-wave7-e2-venv/bin/python manage.py test tests.editorial_demo.test_preview tests.editorial_demo.test_pipeline_preview tests.editorial_demo.test_worklist tests.editorial_demo.test_synthetic_batch tests.editorial_demo.test_review_fixes tests.editorial_demo.test_wave7_review_off --noinput --settings=config.settings.test
/tmp/fatwa-wave7-e2-venv/bin/python tools/dev/wave4_qa.py --wave3 --json /tmp/w7-e2-wave4.json
git diff --check
```

Results: foundation pure 25/25; editorial default-off/legacy **67/67** (61 legacy +6
new, including no-DB CLI parser/ack/action/reason validation); existing D6/C6 dispatcher PASS; diff check PASS. No-DB discovery is separate
from the two DB labels. Actual counts/clean tested SHA from fresh committed-head
reruns and CI links are published with the PR handoff.

## Coordination, limits and held gates

E5 must wire exactly the shared flag/route proposal in CONTRACT.md (new route
before the old generic editorial route), plus the **6-method** no-DB label and the
**16+12 method** DB labels in their separate matrices. Until then the optional view
is exercised through the owned test URLconf; default/global routes stay unchanged.
No missing/zero-suite fallback. E4/E6 can consume the DTO and native #stored-batch,
#stored-q, #stored-intake, #stored-review, #stored-page-size, #wave7-persisted hooks.

NOT_RUN: combined E1–E6 service assembly, real browser/E6, Windows local execution,
whole Wave7 acceptance, fresh independent Astra review and real-source acceptance.
CI state is checked after publication, never inferred from earlier heads. No
main merge/deployment, PR58 metadata edit, source reimport or credential grant.
MAIN_UNCHANGED was checked at fcdc20e1c8f8849e65b9b912d695cb87ab9a0280.
NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED.

## Reconciliation after the recovered complete leadership specification

The complete source arrived after the first local commit. No restart or shared
change was needed. One concrete difference was corrected: the required command
is `wave7_review transition`, not the initially implemented bare options form.
A two-test RED run observed the bare form succeeding (1 failure) and the required
subcommand being rejected (1 error). The command now requires the transition
subparser; bare commands fail before service execution. CLI service/guard/atomic
behavior is unchanged. The initial local commit is retained and the correction
is additive. No migration/storage/status/reference/guard semantics changed.

When selecting settings explicitly, use Django's global option before the
subcommand, e.g. `python manage.py wave7_review
--settings=config.settings.wave7_development transition --item UUID --operation
UUID --action start_review --expected-status UNREVIEWED --reason 'Synthetic'
--synthetic-fixtures-only`, or set DJANGO_SETTINGS_MODULE in the environment.

## Local actual-E4 adapter follow-up

The publication/flag/label statements above describe the prior b55 increment.
The unpublished local adapter now uses the single E4 read gate; see
[E4_ADAPTER_EVIDENCE.md](E4_ADAPTER_EVIDENCE.md) for actual composed tests and
[CONTRACT.md](CONTRACT.md) for the superseding E5 configuration/label proposal.
Publication remains held. No new remote SHA/CI or independent review is claimed.
