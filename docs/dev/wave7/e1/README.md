# Wave7 E1: persistent synthetic intake

Accepted foundation: `34355f5173667c6167351cf379ad56957d7f35f3` on
`codex/20261017-wave7-e5-foundation`; lane `codex/20261017-wave7-e1`.
The approved lossless override supersedes the historical pending wording in E5
docs. No foundation/schema/guard/migration changes are made by E1.

## Public service contract

```python
from apps.intake_workflow.intake import check_intake, import_intake

check_intake(raw: bytes, *, synthetic_fixtures_only: bool = False) -> CheckedIntake
import_intake(raw: bytes, *, idempotency_key: str,
              synthetic_fixtures_only: bool = False, using: str = 'default') -> IntakeResult
```

`CheckedIntake` has `parsed: ParsedPayload`, `items: tuple[CheckedItem,...]` and
`report() -> dict`. Each `CheckedItem` has `row_ordinal`, nullable valid
`external_id`, nullable original string `question_original`, `source: SourceSlice`,
`intake_status`, `validation_results` and `references: tuple[SourceSlice,...]`.
All source offsets are absolute zero-based/end-exclusive UTF-8 byte offsets.
Malformed/scalar/null rows and array-valued invalid pointers retain their exact
source tokens and ordinals. Non-array reference values stay in the row source;
they do not create fabricated pointer records.

`IntakeResult` has `batch_id: UUID`, `decision: IdempotencyDecision` (CREATE or
REPLAY), `payload_sha256`, `item_count`, `reference_count`, `summary` and
`report() -> dict`. Reports are bounded JSON-compatible summaries/findings, not
copies of submitted questions/notes/source slices. Callers retain source via
the approved parser or persisted source text/offsets.

Input is the approved `fatwa.wave7.synthetic-intake.v1` envelope, with the
literal payload acknowledgement and separate literal caller acknowledgement.
The scope/source configuration are fixed foundation constants, never arguments
or payload-derived values. Key grammar is `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`.
The 1,000,000-byte, 1,000-row and 100-reference bounds remain unchanged.

## Validation versus source authority

`check_intake` is pure: no files, DB, network, Django setup, media fetching,
fixture seed or source lookup. It uses the approved lossless parser, fixed
trusted reference map and existing D1 preparation for intake readiness.
Duplicate string IDs across the batch block every occurrence. Invalid IDs
become SQL NULL; their complete original token remains in source text. Source
question strings remain exact even on blocked rows; non-string questions become
NULL in the derived column. Original notes remain exact in `original_row`.

D1's older JSON entrypoint is not a lossless numeric parser. E1 therefore sends
one bounded, disposable field-type projection per row to D1: supported strings
and pointer-string fields are unchanged; invalid non-string scalars/numbers
remain invalid as null placeholders in that validation-only view. It never casts
opaque IDs/numbers, performs Decimal arithmetic or serializes a huge integer as
a source string. Cross-row duplicate classification is then applied to every
occurrence. Nested unsupported values cannot force recursive source rewriting.
The projection is never stored, used as original hash input or treated as source
evidence. Original raw bytes, lexical number tokens and SourceSlices alone are
persisted, including huge ints, 73.000000000000001, underflow/extreme exponents.
No global numeric/security limit changes or new dependencies.

D1 C1 eligibility is retained, including strict C2 HTTPS/443 draft eligibility.
Unsupported pointer shapes, including six-field C2 pointers at this C1 intake
boundary, can block readiness while their exact pointer still persists. Later
E3 verification is a separate service/contract; it does not repair input or
imply scholarly approval. E1 initially stores **every reference UNVERIFIED**, with
empty verified identity and citation, including known fixed pointers. READY_FOR_EDITOR
is intake readiness, not source verification, review completion or publication.
No E3 hook is guessed/imported and no catalog is seeded/read during intake.

## Atomic persistence and idempotency

Parsing, bounds and key validation precede any DB action. Then the sole shared
`synthetic_atomic` validates explicit opt-in/prod0/loopback/role/database prefix,
ownership marker and schema readiness **before** opening the outer transaction.
There is no duplicate outer atomic unit and no fixture seed nested inside it.
Caller transactions/unsafe aliases/overrides/unknown databases fail closed.

The fixed `(scope,idempotency_key)` identifies a batch. Exact original SHA256
matching replays its current persisted metadata with no duplicated batch/item/ref;
different raw bytes under that key raise the existing `IdempotencyConflict`
(`code=IDEMPOTENCY_CONFLICT`, `status_code=409`) without mutation. Whitespace
changes in original bytes are payload changes. Distinct keys permit distinct
batches with identical payloads.

A batch insert runs inside one inner savepoint. Only the exact scoped-key unique
constraint is recovered after rollback to that savepoint; the service re-reads
the committed winner and compares SHA. Other integrity errors propagate and
roll back the whole outer unit. All items and references are committed together;
a later failure rolls back the batch/key and every child. No review event/answer/
approval is generated. Stored original source remains protected by foundation
native constraints/triggers.

## CLI

Run only on authorized fabricated files. Both adapters read at most 1,000,001
bytes (one sentinel) and never rewrite the source file. Check needs no DB/write
opt-in and works with an unreachable port and writes disabled:

```sh
.venv/bin/python -m tools.content_intake wave7-check synthetic.json --synthetic-fixtures-only
.venv/bin/python manage.py wave7_intake check synthetic.json --synthetic-fixtures-only --settings=config.settings.wave7_test
```

Import uses only separate Wave7 dev/test settings and a correctly initialized
owned synthetic DB; it never creates/claims/migrates a database implicitly:

```sh
.venv/bin/python manage.py wave7_intake import synthetic.json --synthetic-fixtures-only --idempotency-key E1-demo-001 --settings=config.settings.wave7_development
```

Success writes one JSON report. Contract/guard/read/persistence failure exits
nonzero with sanitized fixed codes; conflict reports status_code 409. No DSN,
submitted question, raw source, input filename or traceback is echoed by the
command's failure handler. Existing C1 commands and bundle behavior are unchanged.

## Test labels and integration handoff

Pure Windows/Linux labels (14 methods, no DB):

```sh
.venv/bin/python -m unittest tests.intake_workflow.test_check tests.intake_workflow.test_cli -v
```

Actual DB label (15 TransactionTestCase methods, PG17/18 only):

```sh
.venv/bin/python manage.py test tests.intake_workflow.test_database --noinput --verbosity=2 --settings=config.settings.wave7_test
```

The test runner is the unchanged guarded E5 runner. It starts from its owned base,
creates a fresh marked exact test DB, applies foundation migrations and drops
only that created test DB. Do not run this label through port-1 pure discovery.
The DB class independently verifies actual test name, role and major version.

E5 coordination required: add the **two explicit pure labels once each** to
existing C6 Ubuntu/Windows steps; append only the DB label to the existing
separate Wave7 PG17/18 job after assembly. No new workflow, optional fallback or
zero-suite success. This lane makes no shared CI/dependency/settings/route patch.
Windows E1 tests remain NOT_RUN until that actual wiring/execution; green
foundation Windows jobs do not cover E1's new labels.

The accepted fixture produces eight items and three UNVERIFIED references:
six BLOCKED_INVALID, one NEEDS_REVIEW, one READY_FOR_EDITOR; zero review events.
E2/E3/E4 may consume the published signatures/models after assembly. Combined
services/browser, fresh independent review and real-source acceptance remain
separate. NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED.
