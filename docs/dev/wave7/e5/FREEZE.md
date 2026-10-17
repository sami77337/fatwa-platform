# Wave7 E5 foundation freeze

Development-only base: `8a362b0ff69dadbac288d05a7cf33d5fdd36951e` on
`codex/20261017-wave6-integrated-candidate`. The PR/handoff records the exact
frozen head. Original Wave6 worktree/head `79149964...` was not changed.
This is schema/contract infrastructure, not intake/review command implementation
or whole-Wave7 acceptance. Parent arranges independent schema review.

## Frozen constants and public Python interfaces

`apps.intake_workflow.contracts` is pure:

```python
CONTRACT_VERSION = 'wave7.intake.v1'
PAYLOAD_SCHEMA = 'fatwa.wave7.synthetic-intake.v1'
SYNTHETIC_SCOPE = 'wave7-synthetic-v1'
SOURCE_CONFIG_ID = 'wave7-fixed-fixtures-v1'
MAX_INPUT_BYTES = 1_000_000
MAX_ITEMS = 1000
MAX_REFERENCES_PER_ITEM = 100
ROW_ORDINAL_START = REFERENCE_ORDINAL_START = 1

parse_synthetic_payload(raw: bytes, *, synthetic_fixtures_only: bool = False) -> ParsedPayload
# ParsedPayload.raw: bytes; payload_sha256: str; items: tuple[object, ...]
ParsedPayload.prepared_bytes() -> bytes  # derived C1/D1 input, not the hash source
idempotency_decision(existing_sha256: str | None, incoming_sha256: str) -> IdempotencyDecision
next_review_status(current: str, action: str) -> ReviewStatus
valid_external_id(value: object) -> str | None
validate_verified_identity(value: object) -> dict
```

The envelope has **exactly** `schema`, `synthetic_fixtures_only: true`, `items`.
Caller acknowledgement must also be literal True. It cannot supply scope or a
source map/config. 1..1000 rows; a row may be individually malformed and is
retained. Only array-valued reference_links are counted against the 100 bound;
wrong per-row types remain validation findings for E1. Duplicate JSON keys,
nonfinite values, malformed UTF-8/lone surrogates and NUL envelopes reject before
storage. NUL cannot be represented in PostgreSQL text/JSONB; no lossy replacement
is performed. Original accepted bytes are the hash/idempotency source.

`IntakeStatus`: RECEIVED, READY_FOR_EDITOR, NEEDS_REVIEW, BLOCKED_INVALID.
`ReferenceStatus`: VERIFIED, UNVERIFIED, MISMATCHED.
`ReviewStatus`: UNREVIEWED, IN_REVIEW, NEEDS_CHANGES, REVIEWED_INTERNAL.

Actions: `start_review` from UNREVIEWED/NEEDS_CHANGES to IN_REVIEW;
`request_changes` from IN_REVIEW to NEEDS_CHANGES; `complete_review` from
IN_REVIEW to REVIEWED_INTERNAL. No answer, approval or publication action.
Intake readiness and reference verification are deliberately independent.
`IdempotencyDecision` is CREATE/REPLAY. Changed SHA raises `IdempotencyConflict`
with `code='IDEMPOTENCY_CONFLICT'`, `status_code=409`; this is a CLI/service
error contract, not an HTTP write endpoint.

## Frozen models and integrity

All four models have UUID `id` primary keys. Related names are part of the freeze.

| Model | Fields and relations |
| --- | --- |
| IntakeBatch | scope; idempotency_key (128 ASCII-safe chars); payload_sha256; original_payload (BinaryField); payload_snapshot (server-derived JSONB); contract_version; source_config_id; created_at |
| IntakeItem | batch FK(PROTECT, related_name=items); row_ordinal; nullable external_id (100 chars, no uniqueness); nullable question_original; nullable original_row JSON; intake_status; review_status; validation_results JSON |
| IntakeReference | intake_item FK(PROTECT, related_name=references); reference_ordinal; nullable original_pointer JSON; reference_status; verification_results JSON; verified_identity JSON; citation_text |
| ReviewEvent | intake_item FK(PROTECT, related_name=review_events); operation_id UUID; action; from_status; to_status; reason (1..2000 nonblank chars); created_at |

Unique: `(scope,idempotency_key)`, `(batch,row_ordinal)`,
`(intake_item,reference_ordinal)`, `(intake_item,operation_id)`. Reference ordinal
is local to each item. No global external-ID uniqueness. Invalid IDs become
NULL; the original value stays in original_row. Non-string questions have NULL
question_original; original_row retains their actual value. Strings, including
blank or blocked-row strings, remain exact (spaces/marks/tabs/newlines).

Migration `0001_initial` defines fields and native constraints; `0002_synthetic_write_guards`
adds the server-derived snapshot, stricter pointer/evidence constraint and SQL
write/original/event guards. It depends on existing reference migration 0002,
without changing that app. Use the two migrations together; the guard refuses
workflow writes until all four DB write triggers are present/enabled.

The database checks original payload length and SHA256 with PostgreSQL built-ins
(no extensions/grants), fixed configuration and bounded ordinals/statuses.
Batch inserts derive payload_snapshot from the exact raw bytes; callers must not
populate it as evidence (refresh_from_db() to inspect the derived value).
Item/ref inserts must match the actual original snapshot at their ordinals;
question text and supplied external IDs must match source values. Updates/deletes
of batch originals, item originals, reference originals and events are rejected.
Derived item/ref states may change only inside the guarded write unit. Events
are append-only through ordinary DML; privileged test teardown/DDL is not an
application API or an advertised tamper-proof audit system.

JSONB snapshots preserve decoded values, not JSON object key order/lexical number
format. Exact source/provenance bytes, including pointer key order, remain in
original_payload and can be recovered with the stable item/reference ordinals.
Never overwrite source bytes or trim original questions.

UNVERIFIED/MISMATCHED refs require empty verified_identity and citation_text.
VERIFIED requires one complete fixed identity plus its corresponding original
C1 or six-field C2 pointer; SQL also requires actual matching synthetic catalog
metadata. E3 still owns full path/pointer resolution and escaped citation
rendering. Stored pins are assertions, not independent archive/source acceptance.
No verified citation is emitted by an E5 service: no such service exists here.

## Sole write guard and owned database lifecycle

`apps.intake_workflow.guards` signatures:

```python
validate_write_configuration(*, synthetic_fixtures_only=False, using='default') -> DatabaseTarget
initialize_synthetic_database(*, synthetic_fixtures_only=False, using='default') -> WriteContext
require_owned_database(*, synthetic_fixtures_only=False, using='default') -> WriteContext
require_synthetic_write(*, synthetic_fixtures_only=False, using='default') -> WriteContext
synthetic_atomic(*, synthetic_fixtures_only=False, using='default')  # context manager yielding WriteContext
```

WriteContext fields: using, database_name, database_oid, fixed scope and fixed
source_config_id. No caller scope/config/connection argument is accepted.
Guard rejects missing/nonliteral acknowledgement, missing/incorrect
FATWA_WAVE7_SYNTHETIC_WRITES=1 or FATWA_PRODUCTION=0, unsafe connection overrides,
non-default alias, wrong engine, nonliteral loopback, wrong role, wrong base/test
names or actual server identity/version, unknown/foreign ownership and an
already-open application transaction. Rejection precedes atomic().

Role is exactly `wave7_synthetic`. Base name matches
`wave7_synthetic_[a-z0-9_]{1,40}`; test name is exactly `test_` + base name. Only
PostgreSQL 17/18, literal 127.0.0.1 and an explicit valid port are accepted.
Settings retain the original configured base/test names even when the test
runner selects the actual test database. No owner/default catalog fallback.

Initializer claims only an empty target after checks, serializing initialization
with an advisory lock. Its immutable ownership marker pins scope/config/version,
actual database name and OID. Known matching nonempty data is accepted without
reset; empty unclaimed, foreign markers and unknown nonempty databases have no
workflow write permission. Marker is an explicit test-environment ownership
assertion, not an external server attestation or a new credential.

Service pattern: parse/validate first, then
`with synthetic_atomic(synthetic_fixtures_only=True):`. The sole guard runs
before transaction.atomic(); a transaction-local application tag enables DB DML
only for that unit and expires on commit/rollback. No role/server/security
setting changes. Commands call services; do not wrap a second independent unit.
E1 may use an inner transaction.atomic() savepoint for uniqueness races, then
re-read the existing scoped key and compare exact SHA after IntegrityError.
E1 owns actual service retry/idempotency orchestration; E2 owns atomic item-status
and event synchronization, review service
and wave7_review command. No placeholder commands or HTTP write routes exist.

## Separate settings, fixtures and test discovery

Only `config.settings.wave7_development` and `wave7_test` register the app.
Default/public/base/security/middleware/URLs are unchanged. Feature flags remain
disabled unless explicitly set. pre_migrate verifies ownership before schema
mutation; the negative actual migrate-command test proves an unknown target gets
no django_migrations table. Pure validation needs no write flag/DB connection.

Fixtures: `synthetic_payload()` returns eight fabricated rows (independent valid
row 7, duplicate-ID pair 1/4, missing/invalid media, invalid IDs/null row).
`trusted_reference_map()` and `trusted_bridge_config()` return fixed D1/D3 typed
maps for three synthetic headings; neither consumes payload/question-derived
configuration. `seed_reference_catalog(*, synthetic_fixtures_only=False) -> int`
guards an idempotent fixed synthetic catalog seed (edition id 7001), rejects
occupied mismatches and never repairs imported/source records. All media uses
example.invalid and is never fetched.

Pure labels (no DB):
`tests.wave7_foundation.test_contracts` (10),
`tests.wave7_foundation.test_guard_config` (8).
DB-only label: `tests.wave7_foundation.test_database` (21), selected exclusively
with wave7_test settings and disposable PG17/18. E1 owns its own tests/intake_workflow
path; this distinct E5 package avoids cross-lane writes or accidental port-1 DB discovery.

Wave7TestRunner claims a fresh exact test DB after verifying the owned base,
rejects any pre-existing test DB/keepdb/parallel reuse, initializes its marker
before migrations, rejects zero cases and drops only its own exact created DB.
Use TransactionTestCase/LiveServerTestCase for database services; TestCase's outer
transaction cannot precede the required write guard. Test fixture teardown is
confined to the disposable DB; persistent synthetic development data is not reset.

CI adds the two pure labels once each to existing C6 Windows/Linux and a separate
B6 PG17/18 foundation job with actual identity proof before migration. Old Wave6
jobs remain unchanged; dependent-lane labels will only be wired after real files
exist. No source/production migration or real data was used.

NOT_RUN: E1/E2 commands/services, E3 full resolution service, E4 persisted search,
E6 real combined browser, combined Wave7 acceptance and independent review.
`NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED`.
