# Wave7 E1 execution evidence

Base `34355f5173667c6167351cf379ad56957d7f35f3`; exact published head belongs in
the Draft PR/Issue50 handoff. Branch `codex/20261017-wave7-e1`; separate Cloud
worktree `/workspace/wave7-e1`, preserving the old Wave6 worktree/head
`c38c7ed6b120de07730cb34a51678f6929305249`. No new standalone Cloud task ID exposed.
No local-desktop/DO/alternate host used. Runtime access verified in the existing
selected ready Cloud environment; quota/usage/published display metadata not
exposed. [Early interface handoff](https://github.com/sami77337/fatwa-platform/issues/50#issuecomment-6228999691).

Python `/usr/bin/python3.13` 3.13.5, uv0.12.23, Node24.19.0. New venv:

```sh
uv --cache-dir /tmp/wave7-e1-uv-cache venv --python /usr/bin/python3.13 .venv
uv --cache-dir /tmp/wave7-e1-uv-cache pip install --python .venv/bin/python --index-url https://pypi.org/simple --no-deps -r requirements.txt
```

Eight existing exact pins installed; no dependency changes. Initial foundation
pure baseline: 25 methods PASS, 0 failure/error/skip using:
`.venv/bin/python -m unittest tests.wave7_foundation.test_contracts tests.wave7_foundation.test_guard_config tests.wave7_foundation.test_lossless -v`.

## RED, then implementation

- `python -m unittest tests.intake_workflow.test_check -v`: one loader error,
  missing `apps.intake_workflow.intake` before implementation (no actual check
  methods ran in this initial RED discovery result).
- `python -m unittest tests.intake_workflow.test_cli -v`: five methods, two
  failures/two errors from missing command/subcommand/JSON output; one refusal
  assertion already passed on the absent command and is not claimed as a fix.
- Actual isolated PG17/18 invocation of the new DB label also returned the
  missing-service ImportError, one loader error each; no actual DB cases ran
  before implementation. Both base databases were already independently owned
  and foundation migrations applied successfully. No fabricated pre-fix DB pass.

After implementing the announced service/commands, pure 13 and real DB13/major
passed. Two later positive robustness cases (exact-million-byte persistence and
unrelated integrity-error propagation) bring actual DB coverage to 15/major.
They are retained positive coverage, not claims of additional observed defects.

A separate final RED probe reproduced an actual public-settings model-import
RuntimeError instead of the shared guard's fixed refusal. Moving the lazy model
import inside the already guarded unit makes public/default settings reject with
`UNTRUSTED_SCOPE_OR_SOURCE_CONFIG` before model import or database access. The
actual subprocess regression now passes, bringing pure coverage to 14 methods.

## Disposable actual PostgreSQL evidence

Official images, new uniquely named E1-labelled containers only. Loopback
published ports; data mount tmpfs (correct PG17/18 image-specific volume).
No existing database/container/source catalog touched and no global cleanup.
Both actual ownership guards/marker/schema and the test runner are unchanged E5.

| Resource | Base / test name | Actual server |
| --- | --- | --- |
| wave7-e1-pg17-f684e90432 | wave7_synthetic_e1_pg17_f684e90432 / test_wave7_synthetic_e1_pg17_f684e90432 | 170011 (PG17.11) |
| wave7-e1-pg18-66bf5a6223 | wave7_synthetic_e1_pg18_66bf5a6223 / test_wave7_synthetic_e1_pg18_66bf5a6223 | 180006 (PG18.6) |

Role: `wave7_synthetic`. Actual task-owned base databases were claimed only while
empty with `initialize_synthetic_database(synthetic_fixtures_only=True)`, followed
by `manage.py migrate --noinput --settings=config.settings.wave7_test`; all six
reference/workflow migrations applied successfully including lossless 0004.
The tests additionally verify the exact created `test_` name/role/server before
any service cases. No inherited credentials/DB/Fatwa overrides are used: temporary
resource helper sanitizes with existing qa.environment, then supplies only its
own recorded loopback flags/config and disposable synthetic fixture password.

Actual commands from checkout root (`run` injects only that recorded resource's
environment; the temporary helper is not a new product runner):

```sh
.venv/bin/python /tmp/wave7-e1-resources.py start 17
.venv/bin/python /tmp/wave7-e1-resources.py start 18
.venv/bin/python /tmp/wave7-e1-resources.py run 17 -c "import django;django.setup();from apps.intake_workflow.guards import initialize_synthetic_database;print(initialize_synthetic_database(synthetic_fixtures_only=True))"
.venv/bin/python /tmp/wave7-e1-resources.py run 18 -c "import django;django.setup();from apps.intake_workflow.guards import initialize_synthetic_database;print(initialize_synthetic_database(synthetic_fixtures_only=True))"
.venv/bin/python /tmp/wave7-e1-resources.py run 17 manage.py migrate --noinput --settings=config.settings.wave7_test
.venv/bin/python /tmp/wave7-e1-resources.py run 18 manage.py migrate --noinput --settings=config.settings.wave7_test
.venv/bin/python /tmp/wave7-e1-resources.py run 17 manage.py test tests.intake_workflow.test_database --noinput --verbosity=2 --settings=config.settings.wave7_test
.venv/bin/python /tmp/wave7-e1-resources.py run 18 manage.py test tests.intake_workflow.test_database --noinput --verbosity=2 --settings=config.settings.wave7_test
```

Final precommit PG17: **15 methods PASS**, 0 failure/error/skip, 16.428s.
PG18: **15 methods PASS**, 0 failure/error/skip, 16.179s. Actual coverage includes
same-hash and differing-hash two-connection uniqueness races, savepoint recovery,
409/no mutation, partial-child rollback/key reuse, unrelated SQL error propagation,
strict guard refusal before atomic/write, complete duplicates/blocked/null rows,
six-thousand-digit ints, Decimal numeric pointers, underflow/extreme exponents,
exact source byte slices and original question whitespace, no catalog seed or
fabricated verification, 1000 rows/100 references and exact 1,000,000-byte
numeric-row import. Command check has a real DB query wrapper that fails on any
query; it passed with writes disabled. CLI import/replay actually persisted once.

## Pure and compatibility results

All below executed with the new Python3.13 venv. Counts are overlapping suites,
not additive unique coverage. No source archive or owner catalog used.

| Command | Result |
| --- | --- |
| `.venv/bin/python -m unittest tests.intake_workflow.test_check tests.intake_workflow.test_cli -v` | 14 PASS, 0 fail/error/skip, 16.201s |
| `.venv/bin/python -m unittest discover -s tests/content_intake -v` | 30 PASS |
| `.venv/bin/python -m unittest discover -s tests/prepared_pipeline -v` | 41 PASS |
| `.venv/bin/python -m unittest discover -s tests/fatwa_drafts -v` | 17 PASS |
| `.venv/bin/python -m unittest discover -s tests/reference_links -v` | 50 PASS; pure/mocked adapter suite |
| `git diff --check` | PASS |

Pure check covers exact million-byte numeric source without process-wide digit
limit changes, original lexical source slices, malformed/duplicate rows,
id/Unicode/control/key handling, acknowledgement, max/excess bytes/rows/refs,
original question/notes, no Django/DB/network requirement. Actual subprocess
commands run with writes disabled and PGPORT=1; they pass check, sanitize failure
codes/filenames, refuse unacknowledged input and never alter input/create output.

## Integration and remaining gates

- E5 must wire two actual pure labels on Windows/Ubuntu and the PG-only label
  into its existing Wave7 job after assembly; exact labels/snippets in README.
  Windows new E1 labels are NOT_RUN here, never inferred from foundation CI.
- No shared models/migrations/contracts/fixtures/guards/settings/routes/CI/root
  dependency changed. No PR58 metadata update. Source slice/parser authority and
  strict numeric/identity/bounds are preserved; no verified-service hook invented.
- Full combined Wave7 services, same-head combined CI, actual browser and fresh
  independent review are NOT_RUN. Real-source/product acceptance remains HOLD.
- Logs are temporary `/tmp/wave7-e1-*`; no lengthy raw logs/private data published.
  Clean committed-head rerun, remote publication/PR URL and cleanup outcomes are
  recorded in the handoff. USAGE_NOT_OBSERVED / NOT_DEPLOYED / GATES_HOLD.
