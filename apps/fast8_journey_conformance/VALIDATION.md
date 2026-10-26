# FAST8 journey-conformance validation

Reviewed base: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (Draft PR #134).
Branch: `codex/20261026-fast8-journey-conformance-pc1`.
Target: `codex/20261026-fast7-ci-integration-pc1`.
Environment: Windows, Python 3.13.15, existing Django 5.2.18 and Ruff 0.17.0.

Final implementation validation:

- Explicit new modules `tests.fast8_journey_conformance.test_services`,
  `.test_cli`, `.test_http` via `manage.py test`, `config.settings.test`:
  **20 passed, 0 failed, 0 skipped**, 27.618 seconds. The four HTTP tests use
  existing routes; packet tests cover all 20 stock pins. Research lookup is
  explicitly substituted with the existing synthetic snapshot; no database claim.
- Directly reused `tests.fast6_journey.test_integration`: **11 passed, 0 failed,
  0 skipped**, 6.494 seconds. No historical broad suite was rerun locally.
- Ruff check and format of all new Python files passed. No dependency changes.
- CLI exercises UTF-8 stdout, selected scenario, bounded stdin, explicit opt-in,
  sanitized failure output and distinct missing-connection exit 3.
- One independent reviewer completed. Its mutable extension-anchor receipt
  finding was fixed with exact bytes validation; regression tests reject both
  bytearray and memoryview. Stale catalog title/path/input/archive pins are also
  covered. No active reviewer or additional agents remain.

Initial command `manage.py test tests.fast8_journey_conformance` failed before
collection because the existing root `tests` is a namespace package. Explicit
module labels above corrected the invocation without changing common files.
The first explicit run passed 18 tests; the final 20-test run includes the two
review follow-ups. Counts are unique test cases, not inflated by repeated runs
or subtests.

Fixture identity: `scenarios.json` commits all full case identities and original
packet hashes observed at the reviewed base. It covers history, intake-1 through
intake-8, fixed synthetic CSV/JSON/JSONL prepared rows, and
`tools/transcript_pipeline/examples/synthetic-manual.json` with input SHA256
`e217c93eac5fa0109e3c4134b478ce3e6500e8723692312a6c14194ccece40ee`.
The manifest is an assertion set, not a new source fixture or owner archive.

The service reports PASS_WITH_GAPS over available boundaries. Persisted review,
permission-to-case binding and transcript-to-stock-queue remain NOT_CONNECTED.
Absent sibling adapters report NOT_CONNECTED / NOT_RUN. Browser and PostgreSQL
acceptance were NOT_RUN locally; owner source archives were NOT_SUPPLIED.
No new UI was introduced and no browser failure was skipped. Actual final-SHA
B6/C6/D6 run statuses and remote SHA are recorded in the Draft PR after push;
unchanged workflows do not explicitly collect the new FAST8 modules.

NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING. No migrations, production writes, role grants,
scholarly decisions, merge or deployment.
