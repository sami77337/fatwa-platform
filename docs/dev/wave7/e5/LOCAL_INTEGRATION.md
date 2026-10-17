# E5 local available-producer increment

Owner instruction: local implementation and tests only; no push, PR, PR58
metadata update, merge to main or deployment. The accepted foundation/producer
heads are preserved as merge ancestors in a new isolated worktree:
`/workspace/fatwa-wave7-e5-local-integration`, branch
`codex/20261017-wave7-e5-local-integration`.

| Input | Exact SHA |
| --- | --- |
| Foundation/base | `34355f5173667c6167351cf379ad56957d7f35f3` |
| E1 | `2678b91a7c7f2e210a7585e6997725432782aa72` |
| E2 / PR61 | `b55c4596506aafd3c3d5c3a3c0fee1450fc2d2c2` |
| E3 / PR60 | `5f4e66facfb672e610faed9cb7d154bed44c9510` |
| E6 / PR59 | `6e28248beceda4ff6f07c90e5fa5aa08c1cd6cc6` |
| Parent of the E5 wiring commit (four clean merges) | `aa06c5754c87ff6632e2529415785d102e19be61` |

No E4 files were imported. The foundation contracts/models/guards/fixtures/source
slices/migrations, root dependencies, AGENTS.md and public/base URL/settings
files have no changes against the accepted foundation. E5's available shared
changes are the separate Wave7 settings flag/URLconf, permanent tests, QA runner,
C6/B6 workflow wiring and these operation/evidence documents.

## Red/green and actual local evidence

Runtime: Cloud Debian 13, Python 3.13.5 (`/usr/bin/python3.13`, venv created with
uv 0.12.23), Node v24.19.0; existing eight exact requirements installed with uv
from PyPI using `--no-deps`. Disposable tmpfs PG17.11 and PG18.6 services use
task-specific IDs, a literal IPv4 loopback port and `wave7_synthetic` role. Their
base names have the E6-dedicated prefix and each test invocation creates/drops
only its own selected fresh test DB. No owner data or archive was used.

| Actual command/group | Local result |
| --- | --- |
| `python -m unittest tests.wave7_foundation.test_integration_wiring -v` before shared wiring | RED: 3 tests, 5 failure entries (4 literal-opt-in subtests + route); public profile case passed |
| Same command after shared wiring | GREEN: 3 passed |
| E3 negative-ancestor case with only `_catalog_projection_conflicts` temporarily patched to return empty | Controlled RED: 1 failed; demonstrates rejected historical omission, no production file changed |
| Actual `tests.wave7_foundation.test_reference_service` on each PG major | 15 passed, 0 skipped |
| `tools/dev/wave7_qa.py --suite database --json REPORT` on each PG major | 94 passed, 0 failed/errors/skipped |
| `tools/dev/wave7_qa.py --suite pure --json REPORT` | 48 passed, 0 skipped, PGPORT=1 |
| `tools/dev/wave7_qa.py --suite editorial-off --json REPORT` | 6 passed, 0 skipped, PGPORT=1 |
| `python -m unittest discover -s tests/dev -p 'test_*.py' -v` | 53 run: 51 passed, 2 Windows CMD skips |
| `tools/dev/wave4_node.py` with actual E6 CDP + keyboard files | 8 passed, 0 skipped |
| `tools/dev/wave3_qa.py --standalone --require-integrated --reports DIR` | C1 30, C2 17, C3 67 passed; importer 84 run/80 passed/4 source skips; no uncollected modules |
| `python -B -m unittest discover -s tests/fiqh_import -v` | 84 run/80 passed/4 missing-owner-archive skips; all 7 modules discovered |
| `tools/dev/wave4_qa.py --wave3 --json REPORT` | Every configured port-1 suite passed; D1 41, D2 61, D3 67, D4 Python 12 + Node 49, D5 18; C6 repeated explicitly |
| Existing full B6 Django labels + `tests.reference_links_db.test_catalog_adapter`, ordinary test settings | 162 passed on each PG major, no skips |
| `tools/dev/qa.py system` | PASS, no system issues |
| `tools/dev/qa.py node` | 117 run: 108 passed, 9 source/Windows skips |
| Wave7 `check --database default`, `makemigrations --check --dry-run`, `migrate --check`, `showmigrations intake_workflow` | PASS on PG17/18, accepted migrations 0001–0004 applied |
| E6 actual `run.py --suite service` | 6 passed on each PG major |
| E6 actual `run.py --suite workflow-service` | 2 passed on each PG major, including real new-process concurrency |
| E6 actual `run.py --suite browser-baseline` | Python wrapper failed on each PG; 4 engine cases NOT_RUN, 0 browser passes/skips |
| E6 actual `run.py --suite browser` | Python wrapper failed on each PG; 8 engine cases NOT_RUN, 0 browser passes/skips |
| All three workflow YAML files and embedded Python blocks | Syntax checks passed; GitHub Actions execution NOT_RUN |

The full B6 command is:

```sh
python manage.py test tests/reference tests/public_site tests/security \
  tests/integration/api tests/integration/ui \
  tests.integration.source.test_read_only_commands tests.integration.test_site \
  tests.reference_links_db.test_catalog_adapter --noinput --verbosity=2 \
  --settings=config.settings.test
```

Actual E6 commands and required isolation are documented in
[`WAVE7_LOCAL_INTEGRATION.md`](../../../operations/WAVE7_LOCAL_INTEGRATION.md).
Each local call uses `.venv/bin/python` from the explicit Python3.13 venv.
Ignored raw logs/JSON are under `.local/qa/wave7-integration/`; the final handoff
manifest records the actual committed SHA/clean state, paths, patch and bundle.
Initial development reports honestly show merge SHA `aa06c575…` with DIRTY state;
they do not attest the later clean commit. Final validation is reported separately.

The observed Chromium 154.0.8037.57 abort is before DevTools: its SUID sandbox
helper is not configured correctly. Baseline asset preflight passed; persisted
GET returned 200 and all six asset checks passed, proving the former E5 route
blocker is resolved. These HTTP checks do not constitute browser acceptance.
There are no screenshots or browser traffic/keyboard assertions from this blocked
launch. No security setting, sandbox flag, trigger or catalog original was changed.

## Outstanding handoff

E4-dependent implementation/wiring is pending actual published files. Final
desktop/mobile browser evidence, Windows/GitHub CI, real-source checks and fresh
independent combined review remain NOT_RUN. This local increment does not change
PR58 metadata; its earlier title/body update was denied by automatic approval
review because trusted authorization covered Wave6, and was NOT_EXECUTED. The
coordinator now explicitly holds publication, so this action is not retried. No new
PR URL exists for this unpublished integration branch. Publication requires the
owner's separate release of the hold; no alternate comment/publication is used.

Foundation and E3 acceptance were reported by the coordinator; this producer does
not claim independent review of the assembled change, source or product acceptance.
`NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED`.
