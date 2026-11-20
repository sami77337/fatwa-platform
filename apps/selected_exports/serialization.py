"""Explicit transport contracts; no ORM dump, secrets, arbitrary paths or evaluation."""

import io
import re
import zipfile
from hashlib import sha256

from apps.casework.services import CaseConflict
from apps.editorial_export.services import ExportError, encode_csv, encode_json

MAX_ARCHIVE = 8 * 1024 * 1024
COLUMNS = (
    "ordinal",
    "kind",
    "identifier",
    "version_sha256",
    "metadata",
    "content",
    "relationships",
    "files",
)
# Defense in depth for recognizable credentials accidentally present in source
# text. Arbitrary personal information is not automatically redacted: sensitive
# source material requires the independent explicit human-owned grant.
SECRET = re.compile(
    r"(?i)(?:\b(?:authorization\s*:\s*bearer|password|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+|\bbearer\s+[A-Za-z0-9._~+/-]{12,}|\bsk-[A-Za-z0-9_-]{20,}|[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@|[?&](?:token|key|secret|password|credential)=)"
)


def checked(value):
    if isinstance(value, str):
        if SECRET.search(value):
            raise CaseConflict("export_sensitive_marker")
    elif isinstance(value, dict):
        for key, child in value.items():
            checked(key)
            checked(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            checked(child)
    return value


def canonical(value):
    try:
        return encode_json(checked(value))
    except ExportError as exc:
        raise CaseConflict("export_serialization_bound") from exc


def digest(value):
    return sha256(canonical(value)).hexdigest()


def data_file(format, records):
    if any(set(row) != set(COLUMNS) for row in records):
        raise CaseConflict("export_record_schema")
    try:
        if format == "JSON":
            return "records.json", canonical(
                {"schema": "selected-export-records.v1", "records": records}
            )
        if format == "JSONL":
            return "records.jsonl", b"".join(canonical(row) for row in records)
        if format == "CSV":
            checked(records)
            return "records.csv", encode_csv(COLUMNS, records)
    except ExportError as exc:
        raise CaseConflict("export_serialization_bound") from exc
    raise CaseConflict("export_format_invalid")


def archive(*, job, records, files, outcomes):
    name, data = data_file(job.format, records)
    members = {name: data, **files}
    manifest = {
        "schema": "selected-export-manifest.v1",
        "bundle_id": str(job.pk),
        "created_at": job.created_at.isoformat(),
        "expires_at": job.expires_at.isoformat(),
        "scope": "private-selected-resources",
        "format": job.format,
        "files_requested": job.include_files,
        "requested": len(job.selection),
        "included": len(records),
        "outcomes": outcomes,
        "materials": [
            {
                key: row[key]
                for key in (
                    "ordinal",
                    "kind",
                    "identifier",
                    "version_sha256",
                    "relationships",
                    "files",
                )
            }
            for row in records
        ],
        "files": [
            {"path": path, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}
            for path, raw in sorted(members.items())
        ],
        "contract": "Checksums verify bytes, not source authenticity or scholarly correctness. This private data export is not a system backup, public dataset or grant of redistribution rights.",
    }
    members["manifest.json"] = canonical(manifest)
    if sum(map(len, members.values())) > MAX_ARCHIVE:
        raise CaseConflict("export_archive_bound")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as bundle:
        for path, raw in sorted(members.items()):
            if not re.fullmatch(
                r"(?:records\.(?:json|jsonl|csv)|manifest\.json|media/[0-9]{4}\.[a-z0-9]{2,4})",
                path,
            ):
                raise CaseConflict("export_path_invalid")
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            bundle.writestr(info, raw)
    raw = buffer.getvalue()
    if len(raw) > MAX_ARCHIVE:
        raise CaseConflict("export_archive_bound")
    return raw, manifest
