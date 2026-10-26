"""Bounded question-text comparison over authoritative synthetic queue cases."""

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from itertools import combinations

from apps.editorial_queue.services import ORIGINAL_BATCH, QueueRow, build_queue_catalog
from apps.editorial_workbench.batches import PreparedCase
from apps.editorial_workbench.services import WorkbenchCase

MAX_ROWS = 1000
MAX_TEXT_BYTES = 65_536
MAX_TOTAL_BYTES = 2_097_152
MAX_CANDIDATES = 10_000
MAX_ID_CHARS = 256
NORMALIZATION_VERSION = "nfc-arabic-vowels-whitespace-v1"
_VOWELS = frozenset(chr(code) for code in range(0x064B, 0x0653))
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class DuplicateCandidateError(ValueError):
    """Invalid synthetic input, ambiguous provenance, or exceeded resource limit."""


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    case_key: str
    batch_id: str
    row_ordinal: int | None
    source_kind: str
    payload_sha256: str
    source_sha256: str
    source_start: int | None
    source_end: int | None
    external_id: str | None
    field: str
    csv_extra_cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComparedCase:
    source: SourceIdentity
    text: str | None
    text_sha256: str | None
    normalized_sha256: str | None
    transformations: tuple[str, ...]
    exclusion_reason: str | None


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    left_key: str
    right_key: str
    kind: str
    reasons: tuple[str, ...]
    normalized_sha256: str


@dataclass(frozen=True, slots=True)
class BatchCoverage:
    batch_id: str
    row_count: int
    input_sha256: str | None
    input_format: str | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    cases: tuple[ComparedCase, ...]
    candidates: tuple[DuplicateCandidate, ...]
    batches: tuple[BatchCoverage, ...] = ()
    input_scope: str = "supplied_synthetic_queue_rows"

    def to_dict(self) -> dict:
        return {
            "schema": "fatwa.editorial-duplicate-candidates.v1",
            "synthetic_only": True,
            "candidate_only": True,
            "identity_links_created": False,
            "records_merged": False,
            "scholarly_approval": False,
            "published": False,
            "gates": {"B": "NOT_PASSED", "C": "HOLD", "D": "HOLD", "E": "HOLD"},
            "phase01": "BLOCKED",
            "normalization_version": NORMALIZATION_VERSION,
            "input_scope": self.input_scope,
            "summary": {
                "case_count": len(self.cases),
                "compared_count": sum(case.exclusion_reason is None for case in self.cases),
                "excluded_count": sum(case.exclusion_reason is not None for case in self.cases),
                "candidate_count": len(self.candidates),
                "exact_count": sum(c.kind == "exact_text" for c in self.candidates),
                "normalized_count": sum(c.kind == "normalized_text" for c in self.candidates),
                "failed_batch_count": sum(batch.error_code is not None for batch in self.batches),
            },
            "cases": [asdict(case) for case in self.cases],
            "candidates": [asdict(candidate) for candidate in self.candidates],
            "batches": [asdict(batch) for batch in self.batches],
        }

    def json_bytes(self) -> bytes:
        return (
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise DuplicateCandidateError(f"duplicates: {code}")


def _utf8(value: str, *, limit: int, code: str) -> bytes:
    _require(isinstance(value, str), f"{code}_type")
    # Bound before encoding as well as after; lone surrogates fail closed.
    _require(len(value) <= limit, f"{code}_limit_exceeded")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise DuplicateCandidateError(f"duplicates: {code}_invalid_unicode") from exc
    _require(len(encoded) <= limit, f"{code}_limit_exceeded")
    return encoded


def _normalized(text: str) -> tuple[str, tuple[str, ...]]:
    _utf8(text, limit=MAX_TEXT_BYTES, code="text")
    nfc = unicodedata.normalize("NFC", text)
    unvowelled = "".join(char for char in nfc if char not in _VOWELS)
    result = " ".join(unvowelled.split())
    changes = []
    if nfc != text:
        changes.append("unicode_nfc")
    if unvowelled != nfc:
        changes.append("arabic_vowel_marks_removed")
    if result != unvowelled:
        changes.append("whitespace_collapsed")
    return result, tuple(changes)


def normalize_text(text: str) -> str:
    """NFC, remove U+064B..U+0652, collapse Unicode whitespace; preserve letters."""
    return _normalized(text)[0]


def _identity(value: str, code: str) -> None:
    _utf8(value, limit=MAX_ID_CHARS * 4, code=code)
    _require(
        bool(value)
        and len(value) <= MAX_ID_CHARS
        and value == value.strip()
        and not any(unicodedata.category(c).startswith("C") for c in value),
        f"invalid_{code}",
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_source_field")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise DuplicateCandidateError("duplicates: non_finite_source_value")


def _parse_source(raw: str) -> object:
    # A last-value-wins projection cannot establish unambiguous source evidence.
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _source(row: QueueRow, source_bytes: bytes) -> SourceIdentity:
    case = row.case
    _identity(case.key, "case_key")
    _identity(row.batch_id, "batch_id")
    _require(
        isinstance(case.payload_sha256, str) and bool(_DIGEST.fullmatch(case.payload_sha256)),
        "invalid_payload_sha256",
    )
    digest = sha256(source_bytes).hexdigest()
    _require(row.source_sha256 == digest, "source_sha256_mismatch")
    if case.external_id is not None:
        # Invalid intake IDs remain metadata; do not demand intake-valid syntax.
        _utf8(case.external_id, limit=MAX_TEXT_BYTES, code="external_id")

    ordinal, extras, field = None, (), "question"
    if isinstance(case, PreparedCase):
        _require(
            case.batch_id == row.batch_id
            and type(case.row_ordinal) is int
            and 1 <= case.row_ordinal <= MAX_ROWS
            and case.key == f"batch-{case.batch_id}-{case.row_ordinal}",
            "prepared_identity_mismatch",
        )
        _require(case.source_start is None and case.source_end is None, "prepared_source_offsets")
        try:
            original = _parse_source(case.raw_source)
            consistent = original == case.original
        except (ValueError, TypeError, RecursionError) as exc:
            raise DuplicateCandidateError("duplicates: invalid_prepared_original") from exc
        _require(consistent, "prepared_original_mismatch")
        # Serialize only the bounded parsed source, never an unbounded caller object.
        _require(
            json.dumps(original, ensure_ascii=False, sort_keys=True) == case.raw_source,
            "prepared_serialization_mismatch",
        )
        ordinal = case.row_ordinal
        extras = case.csv_extra_cells
        _require(isinstance(extras, tuple) and len(extras) <= MAX_ROWS, "invalid_csv_extra_cells")
        extra_bytes = 0
        for extra in extras:
            extra_bytes += len(_utf8(extra, limit=MAX_TEXT_BYTES, code="csv_extra_cell"))
            _require(extra_bytes <= MAX_TOTAL_BYTES, "total_byte_limit_exceeded")
        if isinstance(original, dict) and "question" not in original:
            field = "title"
        kind = "serialized_prepared_row"
    else:
        _require(row.batch_id == ORIGINAL_BATCH, "fixed_batch_mismatch")
        try:
            original = _parse_source(case.raw_source)
        except (ValueError, RecursionError) as exc:
            raise DuplicateCandidateError("duplicates: invalid_fixed_source") from exc
        if case.key == "history":
            _require(
                case.source_start is None and case.source_end is None, "history_source_offsets"
            )
            _require(case.payload_sha256 == digest, "history_payload_mismatch")
            # The authoritative history adapter serializes one intake in its envelope.
            items = original.get("items") if isinstance(original, dict) else None
            _require(isinstance(items, list) and len(items) == 1, "history_source_shape")
            original = items[0]
            kind = "serialized_history_intake"
        else:
            match = re.fullmatch(r"intake-([1-9][0-9]*)", case.key)
            _require(match is not None, "unsupported_fixed_case_key")
            ordinal = int(match[1])
            _require(ordinal <= MAX_ROWS, "invalid_fixed_ordinal")
            _require(
                type(case.source_start) is int
                and type(case.source_end) is int
                and 0 <= case.source_start < case.source_end
                and case.source_end - case.source_start == len(source_bytes),
                "invalid_source_offsets",
            )
            kind = "original_utf8_slice"

    expected = original.get(field) if isinstance(original, dict) else None
    expected = expected if isinstance(expected, str) else None
    _require(case.question == expected, "question_source_mismatch")
    expected_id = original.get("external_id") if isinstance(original, dict) else None
    expected_id = expected_id if isinstance(expected_id, str) else None
    _require(case.external_id == expected_id, "external_id_source_mismatch")
    return SourceIdentity(
        case.key,
        row.batch_id,
        ordinal,
        kind,
        case.payload_sha256,
        digest,
        case.source_start,
        case.source_end,
        case.external_id,
        field,
        extras,
    )


def detect_candidates(
    rows: Iterable[QueueRow], *, synthetic_fixtures_only: bool = False
) -> DuplicateReport:
    """Compare original question/title text without mutation, joins, or acceptance.

    Callers must supply supported queue-shaped synthetic cases, never private data.
    Supplied payload hashes are provenance assertions, not file verification; the
    built-in adapter obtains them from the authoritative source-verifying service.
    """
    _require(synthetic_fixtures_only is True, "synthetic_fixture_acknowledgement_required")
    cases, normalized_groups = [], {}
    keys, locations, batch_payloads = set(), set(), {}
    byte_count = 0
    for row in rows:
        _require(len(cases) < MAX_ROWS, "row_limit_exceeded")
        _require(isinstance(row, QueueRow), "queue_row_required")
        _require(isinstance(row.case, WorkbenchCase), "workbench_case_required")
        source_bytes = _utf8(row.case.raw_source, limit=MAX_TOTAL_BYTES, code="source")
        text = row.case.question
        text_bytes = _utf8(text, limit=MAX_TEXT_BYTES, code="text") if text is not None else b""
        byte_count += len(source_bytes) + len(text_bytes)
        _require(byte_count <= MAX_TOTAL_BYTES, "total_byte_limit_exceeded")
        source = _source(row, source_bytes)
        # Serialized CSV overflow cells are not part of raw_source; retain and count them.
        byte_count += sum(len(value.encode("utf-8")) for value in source.csv_extra_cells)
        byte_count += len((source.external_id or "").encode("utf-8"))
        _require(byte_count <= MAX_TOTAL_BYTES, "total_byte_limit_exceeded")
        _require(source.case_key not in keys, "duplicate_case_key")
        keys.add(source.case_key)
        location = (source.batch_id, source.source_kind, source.row_ordinal)
        _require(location not in locations, "duplicate_source_location")
        locations.add(location)
        if isinstance(row.case, PreparedCase):
            previous = batch_payloads.setdefault(source.batch_id, source.payload_sha256)
            _require(previous == source.payload_sha256, "batch_payload_mismatch")
        normalized, transformations = _normalized(text) if text is not None else ("", ())
        exclusion = (
            "missing_or_non_text_question"
            if text is None
            else "empty_normalized_text"
            if not normalized
            else "no_letters_or_numbers"
            if not any(char.isalnum() for char in normalized)
            else None
        )
        compared = ComparedCase(
            source,
            text,
            sha256(text_bytes).hexdigest() if text is not None else None,
            sha256(normalized.encode("utf-8")).hexdigest() if text is not None else None,
            transformations,
            exclusion,
        )
        cases.append(compared)
        if exclusion is None:
            normalized_groups.setdefault(normalized, []).append(compared)

    pair_count = sum(len(group) * (len(group) - 1) // 2 for group in normalized_groups.values())
    _require(pair_count <= MAX_CANDIDATES, "candidate_limit_exceeded")
    candidates = []
    for group in normalized_groups.values():
        for left, right in combinations(sorted(group, key=lambda item: item.source.case_key), 2):
            exact = left.text == right.text
            reasons = (
                ("identical_original_text",)
                if exact
                else (
                    "equal_after_conservative_normalization",
                    *sorted(set(left.transformations + right.transformations)),
                )
            )
            candidates.append(
                DuplicateCandidate(
                    left.source.case_key,
                    right.source.case_key,
                    "exact_text" if exact else "normalized_text",
                    reasons,
                    left.normalized_sha256,
                )
            )
    return DuplicateReport(
        tuple(sorted(cases, key=lambda item: item.source.case_key)),
        tuple(sorted(candidates, key=lambda item: (item.left_key, item.right_key))),
    )


def build_duplicate_report(*, synthetic_fixtures_only: bool = False) -> DuplicateReport:
    """Read the fixed catalog once, including failed prepared batch coverage."""
    _require(synthetic_fixtures_only is True, "synthetic_fixture_acknowledgement_required")
    catalog = build_queue_catalog()
    report = detect_candidates(catalog.rows, synthetic_fixtures_only=True)
    batches = []
    seen = set()
    for batch in catalog.batches:
        _require(batch.batch_id not in seen, "duplicate_batch_id")
        seen.add(batch.batch_id)
        members = [case for case in report.cases if case.source.batch_id == batch.batch_id]
        _require(len(members) == batch.total, "batch_count_mismatch")
        source = batch.source
        if source is not None:
            raw = _utf8(source.raw_source, limit=MAX_TOTAL_BYTES, code="batch_source")
            _require(sha256(raw).hexdigest() == source.input_sha256, "batch_source_sha256_mismatch")
            _require(
                source.batch_id == batch.batch_id
                and source.record_count == len(members)
                and all(case.source.payload_sha256 == source.input_sha256 for case in members)
                and (source.error_code is None or not members),
                "batch_provenance_mismatch",
            )
        batches.append(
            BatchCoverage(
                batch.batch_id,
                batch.total,
                source.input_sha256 if source is not None else None,
                source.input_format if source is not None else None,
                source.error_code if source is not None else None,
            )
        )
    _require(all(case.source.batch_id in seen for case in report.cases), "unknown_batch_id")
    return replace(
        report,
        batches=tuple(sorted(batches, key=lambda item: item.batch_id)),
        input_scope="authoritative_fixed_queue_catalog",
    )
