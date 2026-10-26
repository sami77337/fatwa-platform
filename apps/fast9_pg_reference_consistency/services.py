"""Compare ORM-shaped rows with an independently supplied ingest contract."""

from dataclasses import asdict, dataclass
from typing import Protocol

from apps.reference.normalization import normalize_title
from apps.reference.records import MAX_ROWS, PreparedCatalog, prepare_catalog


class CatalogReadUnavailable(RuntimeError):
    """A reader could not supply a complete, independent read-only snapshot."""


@dataclass(frozen=True, slots=True)
class CatalogRows:
    works: tuple[dict, ...]
    editions: tuple[dict, ...]
    headings: tuple[dict, ...]


class CatalogReader(Protocol):
    def read(self, pin: PreparedCatalog, edition_id: int) -> CatalogRows: ...


@dataclass(frozen=True, slots=True)
class ConsistencyResult:
    status: str
    reason: str
    checked_rows: int = 0
    ingest_checksum: str | None = None
    source_acceptance: str = "NOT_CONNECTED"


def validated_pin(pin: PreparedCatalog, edition_id: int) -> PreparedCatalog:
    if type(edition_id) is not int or not 1 <= edition_id <= 2**63 - 1:
        raise ValueError("Explicit edition required")
    if type(pin) is not PreparedCatalog or type(pin.records) is not tuple:
        raise ValueError("Independent prepared contract required")
    if not 1 <= len(pin.records) <= MAX_ROWS:
        raise ValueError("Bounded contract required")
    checked = prepare_catalog(pin.spec, pin.records)
    if checked != pin:
        raise ValueError("Contract checksum/order mismatch")
    return checked


def work_fields(pin: PreparedCatalog) -> dict:
    spec = pin.spec
    return {
        "source_namespace": spec.source_namespace,
        "source_book_id": spec.source_book_id,
        "title_original": spec.work_title,
        "madhhab": spec.madhhab,
    }


def edition_fields(pin: PreparedCatalog) -> dict:
    spec = pin.spec
    return {
        "edition_key": spec.edition_key,
        "title": spec.edition_title,
        "publisher": spec.publisher,
        "source_archive_sha256": spec.source_archive_sha256,
        "source_input_sha256": spec.source_input_sha256,
        "input_name": spec.input_name,
        "ingest_checksum": pin.checksum,
        "heading_count": spec.expected_rows,
        "root_count": spec.expected_roots,
        "max_depth": spec.expected_max_depth,
    }


def _exact(actual: dict, expected: dict) -> bool:
    return (
        type(actual) is dict
        and actual.keys() == expected.keys()
        and all(
            type(actual[key]) is type(value) and actual[key] == value
            for key, value in expected.items()
        )
    )


def _pk(value) -> bool:
    return type(value) is int and 1 <= value <= 2**63 - 1


def compare_rows(pin: PreparedCatalog, edition_id: int, rows: CatalogRows) -> str | None:
    """Return a fixed mismatch code, never row text or connection details.

    Scope is exactly one namespace/book and edition key. Other independent
    works/editions are outside this assertion. Headings include an overflow row.
    """
    if type(rows) is not CatalogRows or any(
        type(part) is not tuple for part in (rows.works, rows.editions, rows.headings)
    ):
        return "snapshot_shape"
    if not rows.works:
        return "work_not_connected"
    if len(rows.works) != 1:
        return "work_count"
    work = rows.works[0]
    if type(work) is not dict or not _pk(work.get("id")):
        return "work_identity"
    if not _exact(work, {"id": work["id"], **work_fields(pin)}):
        return "work_metadata"
    if not rows.editions:
        return "edition_not_connected"
    if len(rows.editions) != 1:
        return "edition_count"
    if type(rows.editions[0]) is dict and rows.editions[0].get("id") != edition_id:
        return "edition_not_connected"
    if not _exact(
        rows.editions[0],
        {
            "id": edition_id,
            "work_id": work["id"],
            **edition_fields(pin),
        },
    ):
        return "edition_metadata"
    if len(rows.headings) != len(pin.records):
        return "heading_count"
    identities = {}
    primary_keys = set()
    for row in rows.headings:
        if type(row) is not dict or not _pk(row.get("id")) or not _pk(row.get("source_row_id")):
            return "heading_identity"
        if row["source_row_id"] in identities or row["id"] in primary_keys:
            return "heading_identity"
        identities[row["source_row_id"]] = row["id"]
        primary_keys.add(row["id"])
    for stored, record in zip(rows.headings, pin.records, strict=True):
        expected = asdict(record)
        parent_row = expected.pop("parent_source_row_id")
        expected.update(
            id=stored["id"],
            edition_id=edition_id,
            parent_id=identities.get(parent_row),
            parent__source_row_id=parent_row,
            parent__edition_id=edition_id if parent_row is not None else None,
            title_normalized=normalize_title(record.title_original),
        )
        if not _exact(stored, expected):
            return "heading_fields_or_parent"
    return None


def check_catalog(
    pin: PreparedCatalog,
    edition_id: int,
    reader: CatalogReader | None = None,
) -> ConsistencyResult:
    """No reader means NOT_CONNECTED. A result never asserts source-owner acceptance."""
    try:
        pin = validated_pin(pin, edition_id)
    except (ValueError, TypeError, AttributeError):
        return ConsistencyResult("NOT_CONNECTED", "invalid_pin")
    if reader is None:
        return ConsistencyResult("NOT_CONNECTED", "reader_required")
    try:
        rows = reader.read(pin, edition_id)
        mismatch = compare_rows(pin, edition_id, rows)
    except CatalogReadUnavailable:
        return ConsistencyResult("NOT_CONNECTED", "catalog_unavailable")
    if mismatch:
        status = "NOT_CONNECTED" if mismatch.endswith("_not_connected") else "INCONSISTENT"
        return ConsistencyResult(status, mismatch)
    return ConsistencyResult("CONSISTENT", "pinned_rows_match", len(pin.records), pin.checksum)
