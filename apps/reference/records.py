"""S1 -> S0 persistence contract. No archive reading, parsing, or source validation."""
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from .normalization import normalize_title

MAX_ROWS = 20_000
MAX_BIGINT = 2**63 - 1


class InvalidCatalog(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CatalogSpec:
    source_namespace: str
    source_book_id: str
    work_title: str
    madhhab: str
    edition_key: str
    edition_title: str
    publisher: str
    source_archive_sha256: str
    source_input_sha256: str
    input_name: str
    expected_rows: int
    expected_roots: int
    expected_max_depth: int


@dataclass(frozen=True, slots=True)
class HeadingRecord:
    source_id: str
    source_row_id: int
    parent_source_row_id: int | None
    source_order: int
    position: int
    depth: int
    source_page_id: int
    source_part: str
    source_page_number: int
    title_original: str
    source_entry_number: int | None = None


@dataclass(frozen=True, slots=True)
class PreparedCatalog:
    spec: CatalogSpec
    records: tuple[HeadingRecord, ...]
    checksum: str


def _text(value: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise InvalidCatalog("Invalid metadata text")


def _integer(value: int, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise InvalidCatalog("Invalid positive integer")


def prepare_catalog(spec: CatalogSpec, records: Sequence[HeadingRecord]) -> PreparedCatalog:
    """Check ORM invariants after S1 validation; preserve every original field."""
    for value, maximum in (
        (spec.source_namespace, 40), (spec.source_book_id, 80), (spec.work_title, 500),
        (spec.madhhab, 100), (spec.edition_key, 100), (spec.edition_title, 500),
        (spec.publisher, 500), (spec.input_name, 255),
    ):
        _text(value, maximum)
    # Logical input basename only: do not persist confidential local filesystem paths.
    if "/" in spec.input_name or "\\" in spec.input_name or ":" in spec.input_name:
        raise InvalidCatalog("input_name must be a logical basename")
    for digest in (spec.source_archive_sha256, spec.source_input_sha256):
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise InvalidCatalog("SHA-256 must be lowercase hexadecimal")
    _integer(spec.expected_rows, MAX_ROWS)
    _integer(spec.expected_roots, MAX_ROWS)
    _integer(spec.expected_max_depth, 5)
    if len(records) != spec.expected_rows:
        raise InvalidCatalog("Heading count does not match validated manifest")
    ordered = tuple(sorted(records, key=lambda row: row.source_order))
    rows: dict[int, HeadingRecord] = {}
    source_ids: set[str] = set()
    orders: set[int] = set()
    positions: set[tuple[int | None, int]] = set()
    for row in ordered:
        _text(row.source_id, 100)
        _text(row.title_original, 500)
        _text(normalize_title(row.title_original), 2000)
        _text(row.source_part, 100)
        for value in (row.source_row_id, row.source_page_id):
            _integer(value, MAX_BIGINT)
        for value in (row.source_order, row.position, row.source_page_number):
            _integer(value, 2**31 - 1)
        _integer(row.depth, 5)
        if row.parent_source_row_id is not None:
            _integer(row.parent_source_row_id, MAX_BIGINT)
        if row.source_entry_number is not None:
            _integer(row.source_entry_number, 2**31 - 1)
        sibling_key = (row.parent_source_row_id, row.position)
        if (row.source_row_id in rows or row.source_id in source_ids
                or row.source_order in orders or sibling_key in positions):
            raise InvalidCatalog("Duplicate source identity/order/position")
        rows[row.source_row_id] = row
        source_ids.add(row.source_id)
        orders.add(row.source_order)
        positions.add(sibling_key)
    for row in ordered:
        if row.parent_source_row_id is None:
            if row.depth != 1:
                raise InvalidCatalog("Root depth must be one")
        else:
            parent = rows.get(row.parent_source_row_id)
            # Strictly decreasing depth to a root also rules out cycles.
            if parent is None or row.depth != parent.depth + 1:
                raise InvalidCatalog("Missing parent or invalid depth/cycle")
    if sum(row.parent_source_row_id is None for row in ordered) != spec.expected_roots:
        raise InvalidCatalog("Root count differs from validated manifest")
    if max(row.depth for row in ordered) != spec.expected_max_depth:
        raise InvalidCatalog("Maximum depth differs from validated manifest")
    canonical = json.dumps(
        {"schema": 1, "spec": asdict(spec), "records": [asdict(row) for row in ordered]},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return PreparedCatalog(spec=spec, records=ordered, checksum=checksum)
