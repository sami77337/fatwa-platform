# Synthetic editorial workflow rehearsal

Run the repository's normal development server on loopback, then open
`http://127.0.0.1:8000/dev/workflow-rehearsal`.
The existing local-only guard rejects production, remote hosts and remote peers.
GET/HEAD select predefined projections; all other HTTP methods return 405.

`intake-7` demonstrates received/preparation, review start, request changes,
restart, and internal completion. Premature completion, an illegal preparation
target, and repeated completion fail through the existing contracts. `history`
retains revisions 1, 2, 4, 7, 9, 11. Missing drafts stay absent.
`?step=0` shows the original state; `?step=N` shows a fixed replay prefix.
Revisiting never retains a previous request's state.

Composition reuses `editorial_workbench.build_cases` (existing intake,
preparation and reference diagnostics), `fatwa_drafts.domain.transition`,
`intake_workflow.contracts.next_review_status`, and
`fatwa_drafts.revision_audit.build_revision_audit` (existing history validation).
Events are frozen dataclasses; reference diagnostics are recursively frozen.
There are no models, migrations, persistent stores, network calls or write APIs.
Existing source text, references and scholarly content are never edited.

Preparation and review are independent contract dimensions. In particular,
`REVIEWED_INTERNAL` neither supplies an answer, resolves a reference, grants
permission, nor represents scholarly approval. Synthetic attribution labels are
not real people or authentication. This is a contract rehearsal, not a proposed
production policy or owner acceptance.

Tests (use the existing Python 3.13 environment):

```powershell
python manage.py test tests.workflow_rehearsal.test_services tests.workflow_rehearsal.test_views tests.workflow_rehearsal.test_browser --settings=config.settings.test --noinput
python manage.py check --settings=config.settings.test
python -m ruff check apps/workflow_rehearsal tests/workflow_rehearsal
python -m ruff format --check apps/workflow_rehearsal tests/workflow_rehearsal
```

The browser test needs Node and sandboxed Chrome (the existing
`FATWA_FASTBUILD_BROWSER` environment override is supported). It reuses the
existing ephemeral WSGI/CDP test harness. `SimpleTestCase` forbids database use.
No PostgreSQL migration or persistent workflow acceptance is claimed.

Fixed fixture identities, not owner archives:

| Fixture | SHA256 |
| --- | --- |
| Wave7 `synthetic_payload()`; `intake-1` through `intake-8` | `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb` |
| Serialized existing `REVISION_HISTORY_RECORD` intake; `history` | `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0` |

Validation on FAST4 base `262fa3d40975cfc0698b045becc2da885760a995` plus
the isolated FAST5 working changes: 469 service/view/regression tests PASS,
including 13 new service/view tests. Real Chrome 155.0.8059.85 rehearsal PASS:
114 requests, nine cases, 1280/375/320px, keyboard navigation, prefix replay,
exact Arabic/CRLF, source hashes and workbench/triage links; zero runtime,
network, HTTP or request-policy errors. The first browser attempt caught an
incorrect new test assumption (existing preparation enum is lowercase
`received`); corrected to the existing contract without changing product code.
The package-only Django test label encountered the repository's namespace-package
discovery limitation (`tests.__file__` is None); use explicit module labels above.
Django checks, scoped Ruff and whitespace checks PASS. Final commit/PR identity
is recorded in the PR; remote CI results must be checked separately.

Combined new tests plus FAST4 integration/browser: 17 PASS. Existing FAST4
Chrome acceptance made 124 requests with unchanged source/export hashes and
zero errors. ONE independent final read-only review found no actionable issues;
it reran 13 service/view tests, nine production/remote guard probes, and eight
malformed-query probes. It inspected browser evidence without rerunning Chrome.

Only one additive include is made in `config/urls.py`; remaining changes are in
this lane's three owned directories. Rollback is code-only. No publication,
deployment, main merge or production data operations.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED / GATES_HOLD.**
