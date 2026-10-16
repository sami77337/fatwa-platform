"""Deterministic full-snapshot comparison; no ORM, writes, exports or repair path."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from itertools import islice
from typing import Any

from apps.reference.normalization import normalize_title
from apps.reference.records import MAX_ROWS, InvalidCatalog, PreparedCatalog, prepare_catalog

# These are the persisted historical fields, including both ID namespaces.
HISTORICAL_FIELDS = (
    "source_id", "source_row_id", "parent_source_row_id", "source_order", "position",
    "depth", "source_page_id", "source_part", "source_page_number", "title_original",
    "source_entry_number",
)
ROW_FIELDS = (*HISTORICAL_FIELDS, "title_normalized", "parent_edition_id")


def expected_metadata(prepared: PreparedCatalog) -> dict[str, Any]:
    spec = prepared.spec
    return {
        "source_namespace": spec.source_namespace,
        "source_book_id": spec.source_book_id,
        "work_title": spec.work_title,
        "madhhab": spec.madhhab,
        "edition_key": spec.edition_key,
        "edition_title": spec.edition_title,
        "publisher": spec.publisher,
        "source_archive_sha256": spec.source_archive_sha256,
        "source_input_sha256": spec.source_input_sha256,
        "input_name": spec.input_name,
        "ingest_checksum": prepared.checksum,
        "heading_count": spec.expected_rows,
        "root_count": spec.expected_roots,
        "max_depth": spec.expected_max_depth,
    }


def _same(actual: Any, expected: Any) -> bool:
    # bool == int and numeric coercion must never hide changed historical identities.
    return type(actual) is type(expected) and actual == expected


def audit_catalog(
    prepared: PreparedCatalog,
    metadata: Mapping[str, Any],
    stored_rows: Iterable[Mapping[str, Any]],
    *,
    max_issues: int = 20,
) -> dict[str, Any]:
    """Compare every source row even when the stored checksum already matches.

    Input rows use ROW_FIELDS; parent_edition_id catches cross-edition FK edges.
    Diagnostics contain IDs and field names only, never a bulk title/source export.
    The caller supplies a deterministic row order and a consistent database snapshot.
    """
    if type(max_issues) is not int or not 1 <= max_issues <= 100:
        raise ValueError("max_issues must be 1..100")
    checked = prepare_catalog(prepared.spec, prepared.records)
    if checked.checksum != prepared.checksum:
        raise InvalidCatalog("Prepared source checksum changed before audit")
    expected = {row.source_row_id: row for row in checked.records}
    edition_id = metadata.get("edition_id")
    issues: list[dict[str, Any]] = []
    codes: Counter[str] = Counter()
    fields: Counter[str] = Counter()

    def issue(code: str, **details: Any) -> None:
        codes[code] += 1
        if len(issues) < max_issues:
            issues.append({"code": code, **details})

    if type(edition_id) is not int or edition_id < 1:
        issue("INVALID_EDITION_ID")
    changed_metadata = [
        key for key, value in expected_metadata(checked).items()
        if key not in metadata or not _same(metadata[key], value)
    ]
    if changed_metadata:
        issue("METADATA_MISMATCH", fields=changed_metadata)

    seen: set[int] = set()
    matched = scanned = roots = max_depth = 0
    truncated = False
    # Bound unexpected/corrupt snapshots too; never buffer or emit all DB rows.
    for row in islice(stored_rows, MAX_ROWS + 1):
        scanned += 1
        if scanned > MAX_ROWS:
            truncated = True
            issue("ROW_LIMIT_EXCEEDED")
            break
        ident = row.get("source_row_id")
        if type(ident) is not int or ident < 1:
            issue("INVALID_SOURCE_ROW_ID")
            continue
        if ident in seen:
            issue("DUPLICATE_SOURCE_ROW_ID", source_row_id=ident)
            continue
        seen.add(ident)
        if "parent_source_row_id" in row and row["parent_source_row_id"] is None:
            roots += 1
        depth = row.get("depth")
        if type(depth) is int:
            max_depth = max(max_depth, depth)
        incoming = expected.get(ident)
        if incoming is None:
            issue("UNEXPECTED_SOURCE_ROW", source_row_id=ident)
            continue
        values = asdict(incoming)
        values["title_normalized"] = normalize_title(incoming.title_original)
        values["parent_edition_id"] = (
            edition_id if incoming.parent_source_row_id is not None else None
        )
        changed = [
            key for key, value in values.items()
            if key not in row or not _same(row[key], value)
        ]
        if changed:
            fields.update(changed)
            issue("ROW_MISMATCH", source_row_id=ident, fields=changed)
        else:
            matched += 1
    missing = sorted(expected.keys() - seen)
    for ident in missing:
        issue("MISSING_SOURCE_ROW", source_row_id=ident)
    for name, actual, target in (
        ("HEADING_COUNT", scanned, checked.spec.expected_rows),
        ("ROOT_COUNT", roots, checked.spec.expected_roots),
        ("MAX_DEPTH", max_depth, checked.spec.expected_max_depth),
    ):
        if actual != target:
            issue(name, actual=actual, expected=target)
    total_issues = sum(codes.values())
    return {
        "kind": "SOURCE_BOOK_TOC_NOT_FATWAS",
        "valid": not codes,
        "database_audit": "EXACT_MATCH" if not codes else "MISMATCH",
        "database_import": "NOT_RUN",
        "edition_id": edition_id if type(edition_id) is int else None,
        "source_archive_sha256": checked.spec.source_archive_sha256,
        "source_input_sha256": checked.spec.source_input_sha256,
        "input_name": checked.spec.input_name,
        "mapped_checksum": checked.checksum,
        "expected_rows": checked.spec.expected_rows,
        "scanned_rows": scanned,
        "scan_complete": not truncated,
        "matched_rows": matched,
        "missing_rows": len(missing),
        "actual_roots": roots,
        "actual_max_depth": max_depth,
        "historical_fields_compared": list(HISTORICAL_FIELDS),
        "issue_count": total_issues,
        "issue_counts": dict(sorted(codes.items())),
        "field_mismatches": dict(sorted(fields.items())),
        "issues": issues,
        "issues_omitted": total_issues - len(issues),
        "deployment_status": "NOT_DEPLOYED",
        "gates": "GATES_HOLD_PHASE01_BLOCKED",
    }
