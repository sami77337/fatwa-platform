"""Lossless bounded source parsing; no model, authority, file path or network access."""

import csv
import io
import json
import re
import stat
import uuid
import zipfile
from dataclasses import dataclass
from hashlib import sha256

MAX_BYTES = 192000
MAX_ROWS = 20
MAX_COLUMNS = 24
SCHEMA = "fatwa.material-import.v1"
FIELDS = (
    "external_id",
    "kind",
    "title",
    "work_title",
    "edition_label",
    "creator",
    "description",
    "source_locator",
    "provenance",
    "rights_basis",
    "language",
    "source_version",
    "recorded_text",
    "file_member",
    "group",
)
PAYLOAD_FIELDS = FIELDS[1:13]
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}\Z")
FILE_MEMBER = re.compile(r"files/[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
FORBIDDEN = re.compile(
    r"(?:password|credential|secret|token|permission|approval|approved|publish|role)", re.I
)


class ImportInputError(ValueError):
    pass


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ImportInputError("duplicate_json_key")
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(
            raw,
            object_pairs_hook=_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ImportInputError("nonfinite_number")
            ),
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ImportInputError("json_invalid") from exc


def text(value, maximum, *, optional=False):
    if type(value) is not str or len(value) > maximum or (not optional and not value.strip()):
        raise ImportInputError("text_invalid")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ImportInputError("text_invalid") from exc
    if any(ord(char) < 32 and char not in "\t\r\n" for char in value):
        raise ImportInputError("text_invalid")
    return value


def identifier(value):
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        raise ImportInputError("identifier_invalid")
    return value


@dataclass(frozen=True)
class SourceFile:
    path: str
    filename: str
    media_type: str
    sha256: str
    size: int
    raw: bytes

    def pin(self):
        return {
            name: getattr(self, name)
            for name in ("path", "filename", "media_type", "sha256", "size")
        }


@dataclass(frozen=True)
class Parsed:
    columns: tuple[str, ...]
    rows: tuple[dict, ...]
    files: dict[str, SourceFile]
    format: str
    origin: dict | None = None


def _records(raw, suffix):
    try:
        source = raw.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise ImportInputError("utf8_required") from exc
    if suffix == "csv":
        try:
            reader = csv.reader(io.StringIO(source, newline=""), strict=True)
            columns = next(reader)
            if len(set(columns)) != len(columns):
                raise ImportInputError("duplicate_columns")
            rows = []
            for values in reader:
                if len(values) != len(columns):
                    raise ImportInputError("csv_cell_count")
                rows.append(dict(zip(columns, values, strict=True)))
                if len(rows) > MAX_ROWS:
                    raise ImportInputError("row_limit")
        except (csv.Error, StopIteration) as exc:
            raise ImportInputError("csv_invalid") from exc
    elif suffix == "jsonl":
        lines = source.splitlines()
        if not 1 <= len(lines) <= MAX_ROWS or any(not line.strip() for line in lines):
            raise ImportInputError("jsonl_rows_invalid")
        rows = [_json(line) for line in lines]
        columns = list(dict.fromkeys(key for row in rows if type(row) is dict for key in row))
    elif suffix == "json":
        rows = _json(source)
        if type(rows) is not list:
            raise ImportInputError("json_array_required")
        columns = list(dict.fromkeys(key for row in rows if type(row) is dict for key in row))
    else:
        raise ImportInputError("source_format_unsupported")
    if not 1 <= len(rows) <= MAX_ROWS or not 1 <= len(columns) <= MAX_COLUMNS:
        raise ImportInputError("source_bounds")
    for column in columns:
        text(column, 100)
        if FORBIDDEN.search(column):
            raise ImportInputError("privileged_or_secret_column")
    for row in rows:
        if type(row) is not dict or row.get("_synthetic") not in (True, "true"):
            raise ImportInputError("synthetic_row_required")
        # Do not accept bool's numerical equality as an acknowledgement.
        if row["_synthetic"] is not True and row["_synthetic"] != "true":
            raise ImportInputError("synthetic_row_required")
        for key, value in row.items():
            if key == "_synthetic":
                continue
            text(value, 10000, optional=True)
    return tuple(column for column in columns if column != "_synthetic"), tuple(rows)


def parse(raw, filename):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise ImportInputError("source_size")
    text(filename, 160)
    if "/" in filename or "\\" in filename or "\x00" in filename:
        raise ImportInputError("filename_invalid")
    suffix = filename.rsplit(".", 1)[-1].lower()
    files = {}
    if suffix != "zip":
        columns, rows = _records(raw, suffix)
        return Parsed(columns, rows, files, suffix)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if not 2 <= len(entries) <= MAX_ROWS + 2 or len(set(names)) != len(names):
                raise ImportInputError("archive_members")
            if sum(entry.file_size for entry in entries) > MAX_BYTES:
                raise ImportInputError("archive_expanded_size")
            for entry in entries:
                mode = (entry.external_attr >> 16) & 0xFFFF
                if (
                    entry.compress_type != zipfile.ZIP_STORED
                    or entry.flag_bits & 1
                    or entry.is_dir()
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                    or entry.file_size > MAX_BYTES
                ):
                    raise ImportInputError("archive_member_unsafe")
            if "manifest.json" not in names:
                raise ImportInputError("archive_manifest_required")
            manifest = _json(archive.read("manifest.json"))
            if (
                type(manifest) is not dict
                or set(manifest)
                not in (
                    {"schema", "synthetic", "records", "files"},
                    {"schema", "synthetic", "records", "files", "origin"},
                )
                or manifest["schema"] != SCHEMA
                or manifest["synthetic"] is not True
                or manifest["records"] not in {"records.csv", "records.json", "records.jsonl"}
                or type(manifest["files"]) is not list
                or len(manifest["files"]) > MAX_ROWS
            ):
                raise ImportInputError("archive_manifest_invalid")
            for spec in manifest["files"]:
                if type(spec) is not dict or set(spec) != {
                    "path",
                    "filename",
                    "media_type",
                    "sha256",
                    "size",
                }:
                    raise ImportInputError("archive_file_manifest_invalid")
                path = spec["path"]
                if type(path) is not str or FILE_MEMBER.fullmatch(path) is None or path in files:
                    raise ImportInputError("archive_file_path")
                content = archive.read(path)
                if (
                    type(spec["size"]) is not int
                    or spec["size"] != len(content)
                    or type(spec["sha256"]) is not str
                    or spec["sha256"] != sha256(content).hexdigest()
                ):
                    raise ImportInputError("archive_file_integrity")
                text(spec["filename"], 160)
                text(spec["media_type"], 80)
                if "/" in spec["filename"] or "\\" in spec["filename"]:
                    raise ImportInputError("archive_file_name")
                files[path] = SourceFile(**spec, raw=content)
            if set(names) != {"manifest.json", manifest["records"], *files}:
                raise ImportInputError("archive_unmanifested_member")
            columns, rows = _records(
                archive.read(manifest["records"]), manifest["records"].split(".")[-1]
            )
            origin = manifest.get("origin")
            if origin is not None:
                if (
                    type(origin) is not dict
                    or set(origin) != {"schema", "namespace", "prepared_at", "mapping"}
                    or origin["schema"] != "fatwa.material-roundtrip.v1"
                    or type(origin["mapping"]) is not list
                    or len(origin["mapping"]) != len(rows)
                ):
                    raise ImportInputError("roundtrip_origin_invalid")
                identifier(origin["namespace"])
                text(origin["prepared_at"], 100)
                identities = set()
                for item, row in zip(origin["mapping"], rows, strict=True):
                    if (
                        type(item) is not dict
                        or set(item)
                        != {
                            "external_id",
                            "source_item_id",
                            "source_version_id",
                            "source_number",
                            "source_digest",
                            "record_sha256",
                        }
                        or item["external_id"] != row.get("external_id")
                        or item["external_id"] in identities
                        or type(item["source_number"]) is not int
                        or not 1 <= item["source_number"] <= 64
                        or type(item["source_digest"]) is not str
                        or re.fullmatch("[a-f0-9]{64}", item["source_digest"]) is None
                        or item["record_sha256"] != digest(row)
                    ):
                        raise ImportInputError("roundtrip_mapping_invalid")
                    identifier(item["external_id"])
                    for key in ("source_item_id", "source_version_id"):
                        if type(item[key]) is not str or str(uuid.UUID(item[key])) != item[key]:
                            raise ImportInputError("roundtrip_identity_invalid")
                    identities.add(item["external_id"])
            return Parsed(columns, rows, files, "zip", origin)
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError) as exc:
        raise ImportInputError("archive_invalid") from exc


def validate_mapping(mapping, parsed):
    if type(mapping) is not dict or set(mapping) != set(FIELDS):
        raise ImportInputError("mapping_fields")
    for target, column in mapping.items():
        if type(column) is not str or (column and column not in parsed.columns):
            raise ImportInputError("mapping_column")
        if (
            target in {"external_id", "kind", "title", "work_title", "source_version"}
            and not column
        ):
            raise ImportInputError("mapping_required")
    if parsed.origin and mapping != default_mapping(parsed):
        raise ImportInputError("roundtrip_exact_mapping_required")
    return mapping


def default_mapping(parsed):
    return {key: key if key in parsed.columns else "" for key in FIELDS}


def mapped(row, mapping, *, provenance, rights_basis):
    values = {key: row.get(column, "") if column else "" for key, column in mapping.items()}
    external_id = identifier(values.pop("external_id"))
    member = values.pop("file_member")
    group = values.pop("group") or external_id
    identifier(group)
    values["provenance"] = values["provenance"] or provenance
    values["rights_basis"] = values["rights_basis"] or rights_basis
    values["language"] = values["language"] or "ar"
    values["synthetic"] = True
    return external_id, group, member, values
