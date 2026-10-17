"""Frozen Wave7 pure contracts. No database, caller-derived scope or source lookup."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from .source_slices import SourceSlice, source_slices

CONTRACT_VERSION = 'wave7.intake.v1'
PAYLOAD_SCHEMA = 'fatwa.wave7.synthetic-intake.v1'
PREPARED_SCHEMA = 'fatwa.prepared-intake.v1'
SYNTHETIC_SCOPE = 'wave7-synthetic-v1'
SOURCE_CONFIG_ID = 'wave7-fixed-fixtures-v1'
DATABASE_ROLE = 'wave7_synthetic'
MAX_INPUT_BYTES = 1_000_000
MAX_ITEMS = 1000
MAX_REFERENCES_PER_ITEM = 100
ROW_ORDINAL_START = REFERENCE_ORDINAL_START = 1
MAX_REASON_CHARS = 2000
# Python 3.13 str.strip() whitespace, explicitly mirrored at the DB boundary.
EXTERNAL_ID_EDGE_WHITESPACE = ''.join(map(chr, (
    *range(9,14), *range(28,33), 0x85, 0xa0, 0x1680, *range(0x2000,0x200b),
    0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
)))


class ContractError(ValueError):
    code = 'INVALID_SYNTHETIC_INPUT'
    status_code = 400


class IdempotencyConflict(ContractError):
    code = 'IDEMPOTENCY_CONFLICT'
    status_code = 409


class IntakeStatus(StrEnum):
    RECEIVED = 'RECEIVED'
    READY_FOR_EDITOR = 'READY_FOR_EDITOR'
    NEEDS_REVIEW = 'NEEDS_REVIEW'
    BLOCKED_INVALID = 'BLOCKED_INVALID'


class ReferenceStatus(StrEnum):
    VERIFIED = 'VERIFIED'
    UNVERIFIED = 'UNVERIFIED'
    MISMATCHED = 'MISMATCHED'


class ReviewStatus(StrEnum):
    UNREVIEWED = 'UNREVIEWED'
    IN_REVIEW = 'IN_REVIEW'
    NEEDS_CHANGES = 'NEEDS_CHANGES'
    REVIEWED_INTERNAL = 'REVIEWED_INTERNAL'


class ReviewAction(StrEnum):
    START_REVIEW = 'start_review'
    REQUEST_CHANGES = 'request_changes'
    COMPLETE_REVIEW = 'complete_review'


class IdempotencyDecision(StrEnum):
    CREATE = 'CREATE'
    REPLAY = 'REPLAY'


REVIEW_TRANSITIONS = MappingProxyType({
    ('UNREVIEWED', 'start_review'): 'IN_REVIEW',
    ('NEEDS_CHANGES', 'start_review'): 'IN_REVIEW',
    ('IN_REVIEW', 'request_changes'): 'NEEDS_CHANGES',
    ('IN_REVIEW', 'complete_review'): 'REVIEWED_INTERNAL',
})
SOURCE_IDENTITY = MappingProxyType({
    'source_namespace': 'wave7-synthetic-toc', 'source_book_id': '622',
    'edition_key': 'wave7-synthetic-edition-v1',
    'source_archive_sha256': 'a' * 64, 'source_input_sha256': 'b' * 64,
})
# Explicit numeric mappings, never casts of opaque source strings. Each dict is immutable.
VERIFIED_IDENTITIES = tuple(MappingProxyType(dict(SOURCE_IDENTITY,
    source_id=f'wave7-title-{row}', edition_id=7001, source_row_id=row)) for row in (1, 2, 3))


def validate_verified_identity(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != set(VERIFIED_IDENTITIES[0]):
        raise ContractError('reference: complete_fixed_identity_required')
    if type(value['edition_id']) is not int or type(value['source_row_id']) is not int:
        raise ContractError('reference: explicit_numeric_identity_required')
    if not any(value == dict(expected) for expected in VERIFIED_IDENTITIES):
        raise ContractError('reference: source_identity_mismatch')
    return dict(value)


def valid_external_id(value: object) -> str | None:
    if (not isinstance(value, str) or not 1 <= len(value) <= 100 or value != value.strip()
            or not value.strip() or any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in value)):
        return None
    try:
        value.encode('utf-8')
    except UnicodeError:
        return None
    return value


def idempotency_decision(existing_sha256: str | None, incoming_sha256: str) -> IdempotencyDecision:
    if any(value is not None and (not isinstance(value, str) or
           re.fullmatch('[0-9a-f]{64}', value) is None)
           for value in (existing_sha256, incoming_sha256)) or incoming_sha256 is None:
        raise ContractError('idempotency: exact_sha256_required')
    if existing_sha256 is None:
        return IdempotencyDecision.CREATE
    if existing_sha256 != incoming_sha256:
        raise IdempotencyConflict('IDEMPOTENCY_CONFLICT')
    return IdempotencyDecision.REPLAY


def next_review_status(current: str, action: str) -> ReviewStatus:
    try:
        return ReviewStatus(REVIEW_TRANSITIONS[(current, action)])
    except (KeyError, TypeError) as exc:
        raise ContractError('review: transition_not_allowed') from exc


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError('json: duplicate_key')
        result[key] = value
    return result


def _finite(value):
    raise ContractError('json: nonfinite_number')


def _decimal(token):
    try:
        value=Decimal(token)
        if value.is_finite():
            return value
    except InvalidOperation:
        pass
    # The C implementation stores its exponent in a bounded machine integer.
    # Python's bundled Decimal implementation is the stdlib fallback and can
    # retain larger exponents. Construct a tuple without the global int/str cap.
    from _pydecimal import Decimal as PythonDecimal
    match=re.fullmatch(r'(-?)([0-9]+)(?:\.([0-9]+))?(?:[eE]([+-]?[0-9]+))?',token)
    if match is None:
        raise ContractError('json: invalid_number')
    sign,whole,fraction,exponent=match.groups()
    fraction=fraction or ''
    power=int(Decimal(exponent or '0'))-len(fraction)
    return PythonDecimal((int(bool(sign)),tuple(ord(ch)-48 for ch in whole+fraction),power))


@dataclass(frozen=True, slots=True)
class ParsedPayload:
    raw: bytes
    payload_sha256: str
    items: tuple[object, ...]
    items_source: SourceSlice
    item_sources: tuple[SourceSlice, ...]
    reference_sources: tuple[tuple[SourceSlice, ...], ...]

    def prepared_bytes(self) -> bytes:
        """Derived D1 input only; raw remains the immutable idempotency/hash source."""
        # Reuse the validated original array: exact numeric tokens (including
        # huge ints/underflow exponents), never float/string conversion or growth.
        return (b'{"schema":"'+PREPARED_SCHEMA.encode('ascii')+b'","items":'
                +self.raw[self.items_source.start:self.items_source.end]+b'}')


def parse_synthetic_payload(raw: bytes, *, synthetic_fixtures_only: bool = False) -> ParsedPayload:
    if synthetic_fixtures_only is not True:
        raise ContractError('synthetic_acknowledgement_required')
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_INPUT_BYTES:
        raise ContractError('payload: expected_1_to_1000000_bytes')
    try:
        data = json.loads(raw.decode('utf-8'),object_pairs_hook=_object,parse_constant=_finite,
                          parse_float=_decimal,parse_int=lambda token:int(Decimal(token)))
    except (UnicodeError, ValueError, RecursionError, InvalidOperation) as exc:
        raise ContractError('payload: invalid_json_or_unicode') from exc
    # Validate decoded Unicode without serializing numbers or changing process-wide
    # Python integer limits. Literal backslash-u0000 remains ordinary source text.
    stack = [data]
    while stack:
        value = stack.pop()
        if isinstance(value,str):
            try:
                value.encode('utf-8')
            except UnicodeError as exc:
                raise ContractError('payload: invalid_json_or_unicode') from exc
            if '\x00' in value:
                raise ContractError('payload: unsupported_nul')
        elif isinstance(value,dict):
            stack.extend(value.keys()); stack.extend(value.values())
        elif isinstance(value,list):
            stack.extend(value)
    if (not isinstance(data, dict) or set(data) != {'schema', 'synthetic_fixtures_only', 'items'}
            or data['schema'] != PAYLOAD_SCHEMA or data['synthetic_fixtures_only'] is not True
            or not isinstance(data['items'], list) or not 1 <= len(data['items']) <= MAX_ITEMS):
        raise ContractError('payload: invalid_synthetic_envelope')
    for item in data['items']:
        if isinstance(item, dict):
            links = item.get('reference_links', [])
            if isinstance(links, list) and len(links) > MAX_REFERENCES_PER_ITEM:
                raise ContractError('payload: reference_limit')
    array,items,references = source_slices(raw)
    return ParsedPayload(raw,hashlib.sha256(raw).hexdigest(),tuple(data['items']),array,items,references)
