"""Fail-closed, deterministic preflight over explicit caller-supplied evidence.

The manifest is a caller-trusted expectation, not a signature or approval. Only
generated synthetic bytes can be examined in this wave. A catalog metadata match
never establishes raw source acceptance. This module performs no filesystem I/O.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
import zlib
from dataclasses import dataclass, fields
from hashlib import sha256

from apps.reference.records import CatalogSpec, HeadingRecord, prepare_catalog
from apps.reference_links.bridge import SourceIdentity
from apps.reference_links.resolution import Heading, Outcome, SnapshotCatalog, resolve

MAX_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
_SPEC_FIELDS = {field.name for field in fields(CatalogSpec)}
_ROW_FIELDS = {field.name for field in fields(HeadingRecord)}
_IDENTITY_FIELDS = _SPEC_FIELDS - {
    "source_archive_sha256",
    "source_input_sha256",
    "expected_rows",
    "expected_roots",
    "expected_max_depth",
}
_CHECKS = (
    "manifest",
    "catalog_metadata",
    "catalog_integrity",
    "input_sha256",
    "archive_sha256",
    "archive_member",
    "source_rows",
    "hierarchy",
    "printed_location",
)


@dataclass(frozen=True)
class Check:
    status: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    status: str
    checks: dict[str, Check]
    dataset_id: str | None = None
    source_kind: str | None = None
    expected_sha256: dict[str, str] | None = None
    observed_sha256: dict[str, str] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "fatwa.source-readiness.report.v1",
            "status": self.status,
            "dataset_id": self.dataset_id,
            "source_kind": self.source_kind,
            "scope": "OFFLINE_SYNTHETIC_PREFLIGHT_ONLY",
            "owner_acceptance": "NOT_RUN",
            "database_verification": "NOT_RUN",
            "expected_sha256": self.expected_sha256 or {},
            "observed_sha256": self.observed_sha256 or {},
            "checks": {
                key: {"status": value.status, "reasons": list(value.reasons)}
                for key, value in self.checks.items()
            },
            "gates": {
                "B": "NOT_PASSED",
                "C": "HOLD",
                "D": "HOLD",
                "E": "HOLD",
                "Phase01": "BLOCKED",
                "scope": "SCOPE_DEVIATION_HOLD",
                "deployment": "NOT_DEPLOYED",
            },
        }


def error_report(code: str, status: str = "BLOCKED") -> Report:
    return Report(status, {"invocation": Check(status, (code,))})


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ValueError("nonfinite_json_number")


def _json(raw: bytes, maximum: int = MAX_BYTES) -> dict:
    if type(raw) is not bytes or len(raw) > maximum:
        raise ValueError("invalid_input_size")
    try:
        result = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_nonfinite
        )
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid_json") from exc
    if type(result) is not dict:
        raise ValueError("expected_json_object")
    return result


def _text(value: object, maximum: int = 500) -> bool:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in value)


def _positive(value: object, maximum: int = 2**63 - 1) -> bool:
    return type(value) is int and 1 <= value <= maximum


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _spec(data: object) -> CatalogSpec:
    if type(data) is not dict or set(data) != _SPEC_FIELDS:
        raise ValueError("invalid_spec_fields")
    for key in _IDENTITY_FIELDS:
        if not _text(data[key]):
            raise ValueError("invalid_spec_text")
    if any(char in data["input_name"] for char in "/\\:"):
        raise ValueError("input_name_not_basename")
    for key in ("source_archive_sha256", "source_input_sha256"):
        if not _digest(data[key]):
            raise ValueError("invalid_sha256")
    for key, limit in (
        ("expected_rows", 20000),
        ("expected_roots", 20000),
        ("expected_max_depth", 5),
    ):
        if not _positive(data[key], limit):
            raise ValueError("invalid_expected_counts")
    if data["expected_roots"] > data["expected_rows"]:
        raise ValueError("invalid_expected_counts")
    SourceIdentity(**{field.name: data[field.name] for field in fields(SourceIdentity)})
    return CatalogSpec(**data)


def parse_manifest(raw: bytes) -> dict:
    """Validate all expectations before a CLI is permitted to open synthetic bytes."""
    data = _json(raw, MAX_MANIFEST_BYTES)
    if (
        set(data)
        != {"schema", "dataset_id", "source_kind", "edition_id", "spec", "catalog_checksum"}
        or data["schema"] != "fatwa.source-readiness.manifest.v1"
    ):
        raise ValueError("invalid_manifest_schema")
    if (
        not _text(data["dataset_id"], 255)
        or data["source_kind"] not in ("synthetic", "owner_supplied")
        or not (
            _positive(data["edition_id"])
            or (data["source_kind"] == "owner_supplied" and data["edition_id"] is None)
        )
        or not _digest(data["catalog_checksum"])
    ):
        raise ValueError("invalid_manifest_identity")
    spec = _spec(data["spec"])
    if data["source_kind"] == "synthetic" and not (
        spec.source_namespace.startswith("synthetic-") and spec.edition_key.startswith("synthetic-")
    ):
        raise ValueError("synthetic_namespace_required")
    return data


def _rows(data: object) -> tuple[HeadingRecord, ...]:
    if type(data) is not list or not 1 <= len(data) <= 20000:
        raise ValueError("invalid_source_rows")
    result = []
    for row in data:
        if type(row) is not dict or set(row) != _ROW_FIELDS:
            raise ValueError("invalid_row_fields")
        for key in ("source_id", "title_original", "source_part"):
            if not _text(row[key]):
                raise ValueError("invalid_row_text")
        for key in _ROW_FIELDS - {"source_id", "title_original", "source_part"}:
            if key in ("parent_source_row_id", "source_entry_number") and row[key] is None:
                continue
            if not _positive(row[key]):
                raise ValueError("invalid_row_integer")
        result.append(HeadingRecord(**row))
    return tuple(result)


def _printed(spec: CatalogSpec, rows: tuple[HeadingRecord, ...], edition_id: int) -> bool:
    """Reuse the resolver with full exact paths, only after hierarchy validation."""
    by_id = {row.source_row_id: row for row in rows}
    headings = []
    locations = {}
    for row in rows:
        location = (row.source_part, row.source_page_number)
        if locations.setdefault(row.source_page_id, location) != location:
            return False
        path = [row.title_original]
        parent = row.parent_source_row_id
        while parent is not None:
            ancestor = by_id[parent]
            path.insert(0, ancestor.title_original)
            parent = ancestor.parent_source_row_id
        headings.append(
            Heading(
                edition_id,
                row.source_row_id,
                spec.work_title,
                row.title_original,
                row.source_part,
                row.source_page_number,
                tuple(path),
                spec.source_namespace,
                spec.source_book_id,
                spec.source_input_sha256,
                spec.edition_key,
                spec.source_archive_sha256,
            )
        )
    catalog = SnapshotCatalog(headings)
    return all(
        resolve({"edition_id": edition_id, "source_row_id": row.source_row_id}, catalog).outcome
        == Outcome.VERIFIED
        for row in rows
    )


def _archive_member(raw: bytes, input_name: str, expected: bytes) -> bool:
    """One bounded synthetic ZIP member, read in memory; never extract to disk."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                return False
            entry = entries[0]
            if (
                entry.filename != input_name
                or entry.is_dir()
                or entry.flag_bits & 1
                or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or entry.file_size > MAX_BYTES
            ):
                return False
            with archive.open(entry) as stream:
                member = stream.read(MAX_BYTES + 1)
            return len(member) == entry.file_size and member == expected
    except (
        OSError,
        ValueError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        EOFError,
        zlib.error,
    ):
        return False


def preflight(
    manifest: bytes | None,
    snapshot: bytes | None = None,
    input_bytes: bytes | None = None,
    archive_bytes: bytes | None = None,
) -> Report:
    """Evaluate metadata and raw bytes separately. No I/O, repair, or inference.

    FAIL takes precedence over missing prerequisites (BLOCKED). With no manifest,
    the entire check is NOT_RUN. PASS is synthetic-only and never changes gates.
    """
    checks = {key: Check("NOT_RUN", ("prerequisite_missing",)) for key in _CHECKS}
    if manifest is None:
        checks["manifest"] = Check("NOT_RUN", ("manifest_missing",))
        return Report("NOT_RUN", checks)
    try:
        expected = parse_manifest(manifest)
    except (ValueError, TypeError):
        checks["manifest"] = Check("FAIL", ("invalid_manifest",))
        return Report("FAIL", checks)
    checks["manifest"] = Check("PASS")
    spec = _spec(expected["spec"])
    pins = {
        "input": spec.source_input_sha256,
        "archive": spec.source_archive_sha256,
        "catalog": expected["catalog_checksum"],
    }
    observed = {}
    catalog_rows = None
    if snapshot is None:
        checks["catalog_metadata"] = Check("BLOCKED", ("catalog_snapshot_missing",))
    else:
        try:
            data = _json(snapshot)
            if (
                set(data) != {"schema", "edition_id", "spec", "records"}
                or data["schema"] != "fatwa.source-readiness.snapshot.v1"
                or not _positive(data["edition_id"])
            ):
                raise ValueError("invalid_snapshot")
            actual_spec = _spec(data["spec"])
            differences = tuple(
                key for key in sorted(_SPEC_FIELDS) if data["spec"][key] != expected["spec"][key]
            )
            if data["edition_id"] != expected["edition_id"]:
                differences += ("edition_id",)
            checks["catalog_metadata"] = (
                Check("FAIL", differences) if differences else Check("PASS")
            )
            catalog_rows = _rows(data["records"])
            prepared = prepare_catalog(actual_spec, catalog_rows)
            checks["catalog_integrity"] = (
                Check("PASS")
                if prepared.checksum == expected["catalog_checksum"]
                else Check("FAIL", ("stale_catalog_checksum",))
            )
        except (ValueError, TypeError):
            checks["catalog_integrity"] = Check("FAIL", ("invalid_catalog_snapshot",))
            catalog_rows = None

    if expected["source_kind"] == "owner_supplied":
        for key in _CHECKS[3:]:
            checks[key] = Check("NOT_RUN", ("owner_raw_evidence_not_examined",))
        status = "FAIL" if any(c.status == "FAIL" for c in checks.values()) else "BLOCKED"
        return Report(status, checks, expected["dataset_id"], "owner_supplied", pins, {})

    for name, raw in (("input", input_bytes), ("archive", archive_bytes)):
        key = f"{name}_sha256"
        if raw is None:
            checks[key] = Check("NOT_RUN", (f"{name}_evidence_missing",))
        elif type(raw) is not bytes or len(raw) > MAX_BYTES:
            checks[key] = Check("FAIL", (f"{name}_size_invalid",))
        else:
            observed[name] = sha256(raw).hexdigest()
            checks[key] = (
                Check("PASS")
                if observed[name] == pins[name]
                else Check("FAIL", (f"{name}_sha256_mismatch",))
            )
    if checks["input_sha256"].status == checks["archive_sha256"].status == "PASS":
        matches = _archive_member(archive_bytes, spec.input_name, input_bytes)
        checks["archive_member"] = (
            Check("PASS") if matches else Check("FAIL", ("archive_member_mismatch",))
        )
    if checks["input_sha256"].status == "PASS":
        try:
            raw_data = _json(input_bytes)
            if (
                set(raw_data) != {"schema", "identity", "records"}
                or raw_data["schema"] != "fatwa.source-readiness.rows.v1"
                or raw_data["identity"] != {key: expected["spec"][key] for key in _IDENTITY_FIELDS}
            ):
                raise ValueError("raw_source_identity_mismatch")
            raw_rows = _rows(raw_data["records"])
            prepare_catalog(spec, raw_rows)
            checks["hierarchy"] = Check("PASS")
            checks["printed_location"] = (
                Check("PASS")
                if _printed(spec, raw_rows, expected["edition_id"])
                else Check("FAIL", ("printed_location_invalid",))
            )
            if catalog_rows is None:
                checks["source_rows"] = Check("BLOCKED", ("valid_catalog_rows_required",))
            elif sorted(raw_rows, key=lambda row: row.source_order) != sorted(
                catalog_rows, key=lambda row: row.source_order
            ):
                checks["source_rows"] = Check("FAIL", ("source_rows_mismatch",))
            else:
                checks["source_rows"] = Check("PASS")
        except (ValueError, TypeError):
            checks["source_rows"] = Check("FAIL", ("invalid_raw_source_rows",))
    status = "PASS"
    if any(check.status == "FAIL" for check in checks.values()):
        status = "FAIL"
    elif any(check.status != "PASS" for check in checks.values()):
        status = "BLOCKED"
    return Report(status, checks, expected["dataset_id"], "synthetic", pins, observed)
