# Approved lossless numeric storage — candidate awaiting Astra review

Same branch/PR58. Supersedes only source field types and numeric/source-slice
representation from the prior foundation; statuses, identities, fixed maps,
scope, byte/row/reference bounds and other finalized rules are unchanged.
Leadership supplied LOSSLESS_NUMERIC_STORAGE — APPROVED verbatim on
2026-10-17 02:48 UTC, request receipt `581fb9e3-c1eb-4b6e-aee5-5527e28ef749`,
response receipt `c2bdbb01-aec7-49e2-9f54-d2151e5fdeed`.
This is supplied authorization, not a claim that this executor read/wrote another chat.

## Exact public Python/source interfaces

```python
parse_synthetic_payload(raw: bytes, *, synthetic_fixtures_only: bool = False) -> ParsedPayload

@dataclass(frozen=True, slots=True)
class SourceSlice:
    start: int
    end: int
    text: str

@dataclass(frozen=True, slots=True)
class ParsedPayload:
    raw: bytes
    payload_sha256: str
    items: tuple[object, ...]
    items_source: SourceSlice
    item_sources: tuple[SourceSlice, ...]
    reference_sources: tuple[tuple[SourceSlice, ...], ...]

ParsedPayload.prepared_bytes() -> bytes
```

All offsets are **absolute zero-based UTF-8 byte offsets, end exclusive**, into
ParsedPayload.raw / IntakeBatch.original_payload. They are not character indices.
For every SourceSlice, `raw[s.start:s.end] == s.text.encode('utf-8')`.
item_sources corresponds one-for-one to items, including invalid scalar/null
rows. reference_sources has one tuple per item; non-object rows, absent or
non-array reference_links yield an empty tuple, preserving the invalid source
row itself. List-valued invalid references, including null/scalars, have exact
source slices and can persist as UNVERIFIED without a fabricated citation.

Integers remain int with no new digit limit. Fraction/exponent values use Decimal,
including 73.000000000000001 and 1e-20000. Python's C Decimal has a bounded machine
exponent; for larger exponents the bundled stdlib `_pydecimal.Decimal` fallback
constructs the exact coefficient/exponent tuple. Both expose the Decimal API;
the fallback is a distinct runtime class from the C implementation, so consumers
must not demand a C-extension class or perform mixed-implementation arithmetic.
No arithmetic/inferred numeric ID mapping is authorized here. This detail is
explicitly part of the candidate for independent review. No new dependency or
process-wide decimal/integer/security setting is introduced.

prepared_bytes() changes only the envelope to the existing prepared schema and
reuses the validated original items-array bytes. Numeric tokens remain numbers
with their exact original lexical representation, never quoted strings, zeroed
underflow or rounded floats. It also cannot expand the input beyond the byte
bound. Decoded items is a validation view, not the authority for rewriting source;
mutating that view does not rewrite prepared_bytes or any original source.

## Models and write contract

| Model.field | New representation |
| --- | --- |
| IntakeBatch.original_payload | Unchanged BinaryField; exact input bytes |
| IntakeBatch.payload_sha256 | Unchanged exact SHA256 of original_payload |
| IntakeBatch.payload_snapshot | TextField(default='', editable=False); trigger derives full UTF-8 text; native CHECK re-encodes to exact original bytes |
| IntakeItem.original_row | Non-null TextField; exact item token including internal whitespace/key order/number spelling |
| IntakeItem.source_byte_start / source_byte_end | PositiveIntegerField; absolute half-open byte range, start may be zero, end > start and <= 1,000,000 |
| IntakeReference.original_pointer | Non-null TextField; exact original reference token |
| IntakeReference.source_byte_start / source_byte_end | Same absolute range contract, also within its immutable item's range |

JSON null source is the text `null`, not SQL NULL. Invalid numeric IDs leave
external_id NULL; the complete original row persists with the caller's blocked
status and validation findings. No source trimming, normalization, value coercion,
numeric range rejection or source JSONB comparison is used.

Typical E1 storage values:

```python
parsed = parse_synthetic_payload(raw, synthetic_fixtures_only=True)
source = parsed.item_sources[row_ordinal - 1]
# In the one existing guarded write unit:
IntakeItem.objects.create(
    batch=batch, row_ordinal=row_ordinal,
    original_row=source.text,
    source_byte_start=source.start, source_byte_end=source.end,
    # existing exact question/valid-ID/status/findings fields
)
pointer = parsed.reference_sources[row_ordinal - 1][reference_ordinal - 1]
# IntakeReference original_pointer=pointer.text; source_byte_start/end=pointer.start/end
```

To read decoded source values, parse the batch's original_payload with the approved
parser and index items/reference_links. Default json.loads(float) is not a source
preservation API. E1/E3 must use SourceSlice text/offsets for persistence and
original provenance; derived D1/D3 values must never replace them.

Guard signatures are unchanged: validate_write_configuration,
initialize_synthetic_database, require_owned_database, require_synthetic_write,
synthetic_atomic all take keyword-only synthetic_fixtures_only=False and
using='default'. The sole application guard still precedes transaction.atomic().
Schema readiness now requires the four write tags plus w7_15_unique_json_keys
and w7_16_lossless_json_strings installed/enabled. Owned 0002/0003 databases must
migrate before using the new write contract. Unknown databases still cannot be
claimed/migrated/written; known owned nonempty data is preserved, never reset.

## Additive migration 0004 and source enforcement

0001/0002/0003 remain byte-for-byte unchanged. Atomic 0004 changes the three
fields, adds the four offset columns, restores existing exact text/offsets from
original_payload, replaces source validation functions/triggers and adds native
text/offset checks. The old append-only triggers are transactionally replaced
for the authorized provenance restoration; ordinary write-tag triggers remain
active, and deferred FK checks are validated before later ALTER TABLE operations.
Existing statuses/IDs/events are not reset. Upgrade of a populated owned 0003
fixture is an actual regression, including the old SQL-NULL malformed row.

Storage uses PostgreSQL json for syntax/structural extraction only, never NUMERIC
or JSONB for source numbers. The original-text unique-key guard remains active.
A nonrecursive JSON-string token validation step preserves invalid-Unicode/NUL
rejection without adding a recursive PL/pgSQL stack limit. Verified citations
still require exact C1 or all six C2 identity fields and matching actual fixed
synthetic catalog metadata; verified_identity remains derived/configured JSONB.

Byte ranges must identify the actual ordinal's token, not merely matching bytes
somewhere in the payload. Structural member lookup rejects matching shadow fields
or string contents; ordered array lookup distinguishes identical siblings.
Reference ranges must identify the actual reference within the actual item.
Source texts, offsets, originals and events remain immutable under ordinary DML;
derived item/reference states may change in a guarded transaction.

Migration 0004 is deliberately irreversible: arbitrary newly accepted numeric
tokens cannot be safely downcast to the old JSONB schema. This is a synthetic
development schema only; no owner/production migration or data has been used.

## Validation and review gate

Pure: test_contracts (11), test_guard_config (8), test_lossless (6): **25 methods**.
DB: test_database (21), test_review_regressions (4), test_lossless_db (9): **34**.
Actual counts at the final committed head and CI links belong to the PR handoff.

RED observations: initial lossless pure module 4 methods / 3 errors (missing source
slices and the Python 4300-digit conversion limit); initial DB module 4 / one
failure + two errors on each PG17/18 (JSONField type, old NUMERIC range overflow,
missing slices). Populated migration initially failed deferred-trigger ALTER;
validating pending constraints before schema changes fixed it. A separate C-Decimal
extreme-exponent probe initially failed, then passed using the stdlib fallback.
The owned-old-0003 readiness regression also failed before the added w7_16 check.

Coverage includes exact 1,000,000-byte integer envelope (next byte rejected),
6000-digit integer and 6000-digit exponent, 1e-20000, exact raw/SHA/text/slices,
numeric invalid-ID retention without rollback, escaped keys, UTF-8 byte offsets,
identical rows/references and shadow matches, tampered/out-of-bounds offsets,
source immutability, C1/six-field C2 identity, malformed Unicode/duplicate keys,
deep valid JSON/literal escape preservation, nonempty upgrade and all prior
idempotency/rollback/concurrency/guard regressions.

No final schema freeze or dependent write dispatch until actual PG17/18 tests,
same-head CI and independent Astra acceptance. Whole Wave7 services/commands/browser
and real-source acceptance remain NOT_RUN. NOT_DEPLOYED / GATES_HOLD.
