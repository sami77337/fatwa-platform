# FAST8 transcript queue validation

Base and remote target verified at
`92fa517ecdefe3f1a92a1ab145ff55943474df44`.
Branch: `codex/20261026-fast8-transcript-queue-pc1`.
Draft PR target: `codex/20261026-fast7-ci-integration-pc1`.
Runtime: Windows, Python 3.13.15, Django 5.2.18; existing dependencies only.

## Fabricated fixture identity

`tests/fast8_transcript_queue/fixtures/fabricated_spans.json` contains two manually
authored invented spans: one question and one answer, with no recording or real
case. No owner archive was accessed, copied or reconstructed.

- Exact file SHA256: `01435680b826aa5b76d5ec77255ac266edf69bc487d16a659e0f9cb4ac3b2e5d`
- Source revision SHA256: `d066799ce106fa1a2709c810c0f4257a0eeac45bc6e9f74846fc86c61abf9620`
- Prepared export SHA256: `09c00cd63f390a9775febf9740cc6fc77ebb84705551cdf8348ce1e107257e9f`
- Unchanged external ID: `transcript-e2862df77ccd6f031836f59a841c234893407eb07211b951aa79870e2e14b695`

The fixture uses single-line JSON without a physical newline, keeping its bytes
stable under Windows Git autocrlf without changing shared attributes. Embedded
CRLF remains escaped JSON and is restored exactly by the source parser.
Real CLI smoke run on this exact fixture returned one EPHEMERAL review entry,
zero drafts and empty stderr. CLI tests additionally cover physical CRLF input
bytes and embedded Arabic CRLF text, as well as CSV and JSONL inputs.

## Focused verification

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -B manage.py test tests.fast8_transcript_queue.test_services tests.fast8_transcript_queue.test_contracts tests.fast8_transcript_queue.test_cli tests.transcript_pipeline.test_pipeline tests.transcript_pipeline.test_cli tests.prepared_pipeline.test_pipeline tests.editorial_queue.test_services tests.editorial_queue.test_review_filters --settings=config.settings.test --noinput --verbosity=1
```

Result: **91 collected, 90 passed, 1 skipped, 0 failed**. Django system check:
no issues (0 silenced). These are the 23 new lane tests and 68 directly affected
tests of the reused services/CLI parser/queue selection; no historical full-suite
rerun. New tests alone: **22 passed, 1 skipped**.

The actual skip is `test_symlink_leaf_and_parent_are_rejected`: Windows does not
permit this process to create unprivileged symlinks (`errno 22`). The separate
real Windows parent-junction rejection test passed; no browser test was skipped.

```powershell
python -m ruff check --no-cache apps/fast8_transcript_queue tests/fast8_transcript_queue tools/fast8_transcript_queue
python -m ruff format --check apps/fast8_transcript_queue tests/fast8_transcript_queue tools/fast8_transcript_queue
git diff --check
```

All passed; 10 Python files formatted. Only the three owned directories changed.

Tests cover source-scoped identities, exact Unicode/milliseconds/digests,
question-only preparation, no drafts, legacy 20-case isolation, actual queue
navigation, exact source-reference resolution, absent/orphan references,
overlapping spans, ambiguous pairs, synthetic acknowledgement, 1 MB/1,000 segment
bounds, immutable snapshots, deterministic output and generic CLI error paths.
Contract-drift tests start with complete real upstream outputs and deliberately
break source/segment or prepared bindings to verify fail-closed behavior.

## Recorded unsuccessful commands

- `python -m pytest --version`: pytest is not installed; the project uses the
  available unittest/Django runners, with no dependency installation.
- Initial new-test run before implementation failed because
  `apps.fast8_transcript_queue` did not exist. CLI agent also observed its initial
  missing-module failure before implementing the CLI.
- Initial combined Django invocation used `tests.fast8_transcript_queue` as a
  package discovery label and failed before running tests (`module.__file__` was
  `None` for the repository's namespace `tests` package). The explicit module
  command above corrects discovery without changing shared test configuration.

## Independent review and CI

One independent final code/security review completed with **no concrete findings**.
The reviewer ran 7 focused tests (all passed) for upstream contract drift, exact
evidence, unchanged 20 legacy cases, immutable snapshots and safe malformed-input
CLI failures. These overlap the 91-test run; they are not extra acceptance counts.
Both delegated agents (CLI implementation and independent review) have completed.
Actual remote commit SHA and B6/C6/D6 results are recorded in the PR after push,
rather than guessed before a run exists.

Shared B6/C6/D6 workflows were not modified. They use explicit suite lists and
do not yet include this new lane's tests; the command above is necessary at later
integration. Remote baseline CI results and local lane acceptance are distinct.

## Limits and unchanged gates

No new route/UI: lane browser acceptance **NOT_RUN**. No database path or
migration: PostgreSQL **NOT_RUN**. Owner source archives **NOT_SUPPLIED**.
No real account operations, role grants, policies, source archives, scholarly
answers/approval/publishing, external AI/network services or deployment.

Gate B **NOT_PASSED**; C/D/E **HOLD**; Phase01 **BLOCKED**;
**SCOPE_DEVIATION_HOLD**; **NOT_DEPLOYED**;
U03/U10 **OWNER_APPROVAL_PENDING**.
