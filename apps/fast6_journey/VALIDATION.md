# FAST6 lane 4 validation — 2026-10-25

Baseline: `0eef6b29943364dddae35a193b356ab79a2e2b5e` (FAST5 Draft PR #116).
Branch: `codex/20261025-fast6-journey-pc2`.
Only new files in this lane's three allowed directories are changed.

Local runtime: CPython 3.13.17, Django 5.2.18, repository-pinned development
dependencies installed in a temporary virtual environment outside the worktree.

## Executed checks

```powershell
python -B manage.py test tests/fast6_journey tests.transcript_pipeline.test_pipeline tests.prepared_pipeline.test_batches tests.prepared_pipeline.test_diagnostics tests.prepared_pipeline.test_pipeline tests.editorial_queue.test_services tests.editorial_workbench.test_services tests.editorial_workbench.test_batches tests.editorial_workbench.test_packets tests.reference_triage.test_services tests.research_bridge.test_services tests.workflow_rehearsal.test_services tests.permission_lab.test_services tests.permission_lab.test_sources tests.editorial_export.test_services tests.integration.test_fast5 --settings=config.settings.test --noinput
python -m ruff check apps/fast6_journey tools/fast6_journey tests/fast6_journey
python -m ruff format --check apps/fast6_journey tools/fast6_journey tests/fast6_journey
git diff --check
```

Initial integrated run: **172 tests passed**, zero skips, 39.881 seconds,
including 16 new tests and directly used upstream services. Django system check:
zero issues. Ruff and format checks passed. No PostgreSQL database was created
or used. Final results after the independent review are recorded below.

Chrome actually executed desktop RTL, keyboard skip/previous/next, 320/375px
overflow checks, exact Arabic CRLF, catalog href, closed unverified references,
triage/workbench anchors and query recovery. Application requests were local
GET/HEAD only. Catalog explicitly substituted with existing synthetic snapshot;
no live PostgreSQL catalog match or owner archive acceptance is claimed.

Initial test-first runs failed because the new service/CLI modules were absent.
The first service implementation exposed strict export encoding rejecting the
existing State enum; using the existing packet serializer for draft records
resolved that compatibility failure. No upstream implementation changed.
Two attempted combined test commands failed before executing tests: Django
cannot discover a dotted directory under namespace `tests`, and does not accept
individual file paths. The successful command above uses the lane directory
plus dotted individual modules. An early HTTP assertion also exposed ordinary
workbench HTML CRLF normalization. That upstream limitation remains documented;
exact text is checked in packet HTML/JSON, triage and research.

One independent final review identified an important missing invariant:
investigation references could be swapped between cases while retaining the
correct enclosing case identity. Two new regression tests reproduced ten
failing swap/tamper checks. The verifier now compares occurrence count, ordinal,
raw/contract status, reasons, source text/offsets/hash, original and verified
identities and evidence before bridging. A subsequent run exposed one no-op
test mutation (`{}` was already the fixture's original identity); the test now
supplies a genuinely unrelated identity. No additional independent review round
was performed.

Final integrated rerun of the command above: **174 tests passed**, zero skips,
30.776 seconds (18 new tests). Actual Chrome passed again with the same explicit
synthetic catalog limitation. Final Ruff/format and diff checks passed.

Offline report: 74,814 bytes, SHA256
`82ff4bc88bf1b1f126a2b69bd9b15259e6b818b706b18e405cb8362e0473018e`.
The additional invariant preserves correct output while rejecting forged joins.

## Exact fixture evidence

| Input | SHA256 |
| --- | --- |
| tools/transcript_pipeline/examples/synthetic-manual.json | `e217c93eac5fa0109e3c4134b478ce3e6500e8723692312a6c14194ccece40ee` |
| synthetic-csv | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` |
| synthetic-json | `d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec` |
| synthetic-jsonl | `e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363` |
| synthetic-malformed | `d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086` |

The runtime JSON includes every original/history case identity, source digest,
revision digest, packet digest, permission inventory pin and export file digest.
It intentionally reports browser/HTTP/PostgreSQL as NOT_RUN because the CLI
does not run those separate tests. Reading this validation file is not a runtime
capability or permission grant.

Existing CI workflows use explicit legacy suites; their status must be reported
separately from this new lane's local checks. No workflow change is allowed in
this lane. FAST6 integration must add the documented new test command to its
chosen acceptance runner.

Owner ZIP archives, live PostgreSQL catalog, historical 70 permission rows / 58
transitions, U03/U10 owner acceptance and persisted review linkage remain
unavailable to this journey. Four NOT_CONNECTED boundaries are in README and
the report. No private cases, migrations, publication, deployment or main merge.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD; NOT_DEPLOYED.**
