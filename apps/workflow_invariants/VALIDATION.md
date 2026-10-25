# FAST6 lane 1 validation

Base: `0eef6b29943364dddae35a193b356ab79a2e2b5e` (FAST5 draft PR #116).
Branch: `codex/20261025-fast6-workflow-pc2`.
Local runtime: Windows, Python **3.13.17**. Runtime dependencies installed from
unchanged `requirements.txt` using `--no-deps`; Ruff **0.15.7**. The local virtual
environment is ignored under `tools/workflow_invariants/.venv/`.

## Executed checks

The following commands use `tools/workflow_invariants/.venv/Scripts/python.exe`
as `python` (the initial 70-contract run used `py -V:Astral/CPython3.13.17`).

```powershell
python -m unittest discover -s tests/workflow_invariants -v
python -m unittest tests.fatwa_drafts.test_domain tests.fatwa_drafts.test_revision_audit tests.wave7_foundation.test_contracts tests.revision_core.test_history_navigation tests.revision_core.test_serialization_regressions tests.revision_core.test_unicode_bounds tests.revision_core.test_dependencies -v
python manage.py test tests.workflow_rehearsal.test_services tests.editorial_workbench.test_services --settings=config.settings.test --noinput -v 2
python -m ruff check apps/workflow_invariants tests/workflow_invariants tools/workflow_invariants/cli.py tools/workflow_invariants/__main__.py tools/workflow_invariants/__init__.py --no-force-exclude
python -m ruff format --check apps/workflow_invariants tests/workflow_invariants tools/workflow_invariants/cli.py tools/workflow_invariants/__main__.py tools/workflow_invariants/__init__.py --no-force-exclude
```

- New suite: **22 tests passed** after fixing the independent review finding
  (20 initial tests plus two history-error regressions).
- Existing pure domain/intake/revision suites: **70 tests passed**.
- Existing rehearsal/workbench services: **17 tests passed**. Django system check
  reported zero issues; its unused database was explicitly skipped.
- Ruff check passed; all eight Python files passed the format check.
- Tests execute the real CLI in fresh processes, verify deterministic bytes,
  exercise malformed/bounded input, and check no Django/psycopg import. In-process
  replay is also exercised with file/network operations forbidden.
- Existing nine allowed edges are exercised, without synthesizing historical
  policy. Readiness uses only existing synthetic title/answer fields.

Development failures, subsequently resolved: engine/CLI imports initially failed
before implementation; reference adapter initially expected a history-only key
and was corrected to use the actual source slices and verified identity; fixture
count test failed before files were generated. A Django run launched before the
isolated dependency installation completed failed on missing `asgiref`; the rerun
after successful installation passed all 17 tests. A package-only unittest command
discovered zero tests; the explicit discovery command above ran the actual suite.

## Independent final review

One read-only independent review found one actionable P2: the revision history
validator's `HistoryDataError` could escape the CLI as a traceback. Both initial
and resulting history validation now translate it to an invariant `ReplayError`.
The engine and CLI regression tests reproduced the error before the fix; final
verification uses the new suite of 22 tests. No second review was performed.
No other actionable findings were reported. Owner archives/transitions and
production/PostgreSQL behavior remain explicitly outside supplied evidence;
their gates remain unchanged.

## Exact input identities

`apps.intake_workflow.fixtures.synthetic_payload()` SHA256:
`cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb`.

| Command fixture | File bytes SHA256 | Accepted / rejected |
|---|---|---|
| `rehearsal.json` | `933ab91d942eaad21d24efa40724fd01c23b717144e7b82e0c2e5e07ba9dfcdc` | 5 / 3 |
| `preparation.json` | `e31408d0a1229d1957c553f6d08a57836c2239c2c618fda58c7b5605aeafa091` | 4 / 0 |
| `blocked.json` | `83e1819963856a977cf7cac6bca0e063d5a690c6ce0c83f70ea4618ae12a725e` | 0 / 8 |

These are files under `tools/workflow_invariants/fixtures/`, including their final
LF byte (a directory-local `.gitattributes` preserves LF on checkout). Tests compare
the files with generated scenarios to catch stale commands. Rehearsal uses
`intake-7`, row slice SHA256
`9681a709379599a7deb0e2ebdfb68c297b1642c22402735a5907d7d5e1224f55`.
Blocked uses `intake-1`, row slice SHA256
`9997733aafa7ef2daf20e944fecf31a5057d4c8d48b0575ecdc1fc26b7c96a09`.
Preparation uses `history` serialized intake SHA256
`75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0`.
History is serialized provenance, not an original archive slice. Tests and CLI
reports retain exact payload/row hashes separately from canonical command hashes.

## Limits

No PostgreSQL integration test was run or needed for this in-memory layer.
No claim of whole-repository, browser, database, production or owner acceptance.
Existing shared CI was not edited; lane test integration remains a later lane
integration responsibility. CI status must be read from the actual published SHA.
Historical 58 owner transitions, owner archives and approval evidence:
**NOT_SUPPLIED**. Gate B **NOT_PASSED**, C/D/E **HOLD**, Phase01 **BLOCKED**,
**SCOPE_DEVIATION_HOLD**, **NOT_DEPLOYED**.
