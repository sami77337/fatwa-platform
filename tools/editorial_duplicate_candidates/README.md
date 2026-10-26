# Offline synthetic duplicate candidates

From the repository root, with its existing Python 3.13 environment:

```text
python -B -m tools.editorial_duplicate_candidates --synthetic-fixtures-only
```

The command emits one deterministic UTF-8 JSON document to stdout. It accepts
only the acknowledgement flag and `--help`: no paths, uploads, source discovery,
database, network, persistence, or editorial actions. Exit 0 means report
generation succeeded, including explicit exclusions and malformed-batch coverage;
it does not mean all inputs are valid or that any gate passed. Invalid arguments
exit 2; expected source verification failures exit 1 without emitting a report.
Errors do not echo submitted argument values or source content.

The report uses the authoritative fixed queue service, covering its original
synthetic cases and prepared CSV/JSON/JSONL batches. Candidate endpoints remain
separate canonical case keys. Shared external IDs never establish identity or
text equivalence. See the [service contract](../../apps/editorial_duplicate_candidates/README.md)
for normalization, provenance, limits, and pure-service usage.

## Focused verification

```text
python -B -m unittest discover -s tests/editorial_duplicate_candidates -v
python -m ruff check --no-force-exclude apps/editorial_duplicate_candidates tools/editorial_duplicate_candidates tests/editorial_duplicate_candidates
python -m ruff format --check --no-force-exclude apps/editorial_duplicate_candidates tools/editorial_duplicate_candidates tests/editorial_duplicate_candidates
```

Run the new and directly affected tests on PowerShell using explicit module
labels (this repository's namespace test directories are not package discovery roots):

```powershell
$duplicateTestLabels = @(rg --files tests/editorial_duplicate_candidates tests/editorial_queue tests/prepared_pipeline -g 'test_*.py' | ForEach-Object { ($_ -replace '\\','.' -replace '/','.' -replace '\.py$','') })
$duplicateTestLabels += @('tests.editorial_workbench.test_services', 'tests.editorial_workbench.test_batches')
python -B manage.py test @duplicateTestLabels --settings=config.settings.test --verbosity 1
```

Development baseline: FAST6 PR #121, commit
`667fd70217d794169c23569ce2df0396dcd27f7c`. Fixtures are the existing in-memory
`apps.intake_workflow.fixtures.synthetic_payload`,
`apps.editorial_demo.revision_fixtures.REVISION_HISTORY_RECORD`, and
`apps.editorial_workbench.batch_fixtures.synthetic_inputs`; additional regression
rows are invented in the new test suite. No owner archives or private data are
used. The fixed catalog contains 20 cases, 17 comparable texts, 3 exclusions,
11 exact candidate pairs, and one malformed batch. Normalized-only candidates
are exercised with separate invented regression rows, without changing fixtures.

These tests require no database and do not establish PostgreSQL acceptance.
No migrations or data conversion; rollback removes only the three new modules.
No routing, grants, approvals, publication, deployment, or main merge.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED.
**NOT_DEPLOYED / GATES_HOLD.**
