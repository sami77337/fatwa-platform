"""One bounded immutable bundle shared by offline CLI and guarded HTTP views.

Only existing, code-selected synthetic adapters are read. No uploaded input,
database, network, clock, source-file discovery or editorial mutations.
"""

import csv
import io
import json
import os
from dataclasses import asdict, dataclass
from hashlib import sha256
from urllib.parse import quote

from apps.editorial_workbench.packets import build_packet
from apps.editorial_workbench.services import build_cases, build_prepared_workbench

MAX_CASES = 64
MAX_BATCHES = 16
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_BUNDLE_BYTES = 6 * 1024 * 1024
MAX_NODES = 100_000
MAX_DEPTH = 24
MAX_STRING_CHARS = 131_072
FILE_NAMES = ("report.json", "cases.csv", "batches.csv", "manifest.json")
HOLDS = (
    "Gate B NOT_PASSED",
    "C/D/E HOLD",
    "Phase01 BLOCKED",
    "SCOPE_DEVIATION_HOLD",
    "NOT_DEPLOYED",
)


class ExportError(ValueError):
    """Export cannot safely preserve a complete bounded synthetic snapshot."""


def require_development(synthetic_fixtures_only: bool) -> None:
    if (
        synthetic_fixtures_only is not True
        or os.environ.get("FATWA_PRODUCTION", "0") != "0"
        or os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith(".production")
    ):
        raise ExportError("export: synthetic_development_only")
    # Pure offline CLI also runs without Django installed or initialized.
    try:
        from django.conf import settings
    except ModuleNotFoundError:
        return
    if settings.configured and (
        getattr(settings, "FATWA_PRODUCTION", False)
        or str(getattr(settings, "SETTINGS_MODULE", "")).endswith(".production")
    ):
        raise ExportError("export: synthetic_development_only")


def encode_json(value: object) -> bytes:
    """Canonical strict UTF-8, preserving every source character without truncation."""
    nodes, text_bytes = 0, 0

    def validate(item, depth=0):
        nonlocal nodes, text_bytes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise ExportError("export: structure_limit")
        if type(item) is str:
            if len(item) > MAX_STRING_CHARS:
                raise ExportError("export: text_limit")
            text_bytes += len(item.encode("utf-8", errors="strict"))
            if text_bytes > MAX_FILE_BYTES:
                raise ExportError("export: byte_limit")
        elif item is None or type(item) is bool:
            return
        elif type(item) is int:
            if abs(item) > 2**63 - 1:
                raise ExportError("export: integer_limit")
        elif type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ExportError("export: invalid_key")
                validate(key, depth + 1)
                validate(child, depth + 1)
        elif type(item) in (list, tuple):
            for child in item:
                validate(child, depth + 1)
        else:
            raise ExportError("export: unsupported_value")

    try:
        validate(value)
        raw = (
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            + "\n"
        ).encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ExportError("export: invalid_utf8") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise ExportError("export: byte_limit")
    return raw


def encode_csv(columns: tuple[str, ...], rows: list[dict]) -> bytes:
    """CSV with JSON-valued cells: lossless types, CRLF and formula-like text.

    After csv.reader, json.loads each cell. Text values start with a JSON quote,
    not spreadsheet operators. No apostrophe insertion or source normalization.
    """
    if len(rows) > MAX_CASES or len(columns) > 32:
        raise ExportError("export: csv_structure_limit")
    encode_json(columns)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    writer.writerow(columns)
    parts = [stream.getvalue().encode("utf-8")]
    total = len(parts[0])
    if total > MAX_FILE_BYTES:
        raise ExportError("export: byte_limit")
    for row in rows:
        if set(row) != set(columns):
            raise ExportError("export: csv_columns_mismatch")
        encode_json(row)
        stream.seek(0)
        stream.truncate(0)
        writer.writerow([encode_json(row[key]).decode("utf-8")[:-1] for key in columns])
        raw = stream.getvalue().encode("utf-8", errors="strict")
        total += len(raw)
        if total > MAX_FILE_BYTES:
            raise ExportError("export: byte_limit")
        parts.append(raw)
    return b"".join(parts)


@dataclass(frozen=True, slots=True)
class ExportBundle:
    files: tuple[tuple[str, bytes], ...]

    def file(self, name: str) -> bytes:
        for filename, raw in self.files:
            if filename == name:
                return raw
        raise ExportError("export: unknown_file")

    def report(self) -> dict:
        return json.loads(self.file("report.json"))


def build_export(*, synthetic_fixtures_only: bool = False) -> ExportBundle:
    require_development(synthetic_fixtures_only)
    try:
        return _build_export()
    except (ValueError, TypeError) as exc:
        if isinstance(exc, ExportError):
            raise
        raise ExportError("export: invalid_fixture_data") from exc


def _build_export() -> ExportBundle:
    original = build_cases()
    prepared = build_prepared_workbench()
    cases = (*original, *prepared.cases)
    if len(cases) > MAX_CASES or len(prepared.batches) > MAX_BATCHES:
        raise ExportError("export: inventory_limit")
    if len({c.key for c in cases}) != len(cases):
        raise ExportError("export: duplicate_case_key")
    batch_map = {b.batch_id: b for b in prepared.batches}
    if len(batch_map) != len(prepared.batches):
        raise ExportError("export: duplicate_batch_id")
    batches = []
    for batch in sorted(prepared.batches, key=lambda b: b.batch_id):
        members = [c for c in prepared.cases if c.batch_id == batch.batch_id]
        if (
            sha256(batch.raw_source.encode("utf-8")).hexdigest() != batch.input_sha256
            or batch.record_count != len(members)
            or batch.valid_count != sum(c.intake_state == "valid" for c in members)
            or batch.pending_count != sum(c.intake_state == "pending" for c in members)
            or batch.rejected_count != sum(c.intake_state == "rejected" for c in members)
            or len({c.row_ordinal for c in members}) != len(members)
        ):
            raise ExportError("export: batch_identity_mismatch")
        batches.append(asdict(batch))
    entries = []
    for case in sorted(cases, key=lambda c: c.key):
        packet = build_packet(case, batch_map.get(getattr(case, "batch_id", None)))
        entries.append(
            {
                "packet": packet.payload(),
                "packet_sha256": packet.sha256,
                "navigation": {
                    "case_key": case.key,
                    "packet_path": f"/dev/editorial-workbench/{quote(case.key, safe='')}?packet=html",
                },
            }
        )
    report = {
        "schema": "synthetic-editorial-export.v1",
        "synthetic_only": True,
        "holds": HOLDS,
        "batches": batches,
        "cases": entries,
        "csv_encoding": "UTF-8 without BOM; RFC4180 CRLF; each data cell is canonical JSON",
        "ordering": "batches by exact batch_id; cases by exact case_key; packet arrays retain service order",
        "scope": "fixed_synthetic_fixtures_only_no_persisted_review",
    }
    files = (
        ("report.json", encode_json(report)),
        ("cases.csv", encode_csv(("navigation", "packet", "packet_sha256"), entries)),
        ("batches.csv", encode_csv(tuple(sorted(BatchColumns)), batches)),
    )
    manifest = {
        "schema": "synthetic-editorial-export-manifest.v1",
        "synthetic_only": True,
        "holds": HOLDS,
        "files": {
            name: {"bytes": len(raw), "sha256": sha256(raw).hexdigest()} for name, raw in files
        },
        "batch_inputs": [
            {
                "batch_id": b["batch_id"],
                "input_format": b["input_format"],
                "input_sha256": b["input_sha256"],
            }
            for b in batches
        ],
        "case_inputs": [
            {
                "identity": e["packet"]["identity"],
                "source_kind": e["packet"]["source"]["kind"],
                "source_text_sha256": e["packet"]["source"]["text_sha256"],
                "packet_sha256": e["packet_sha256"],
            }
            for e in entries
        ],
        "verification": "exact-byte replay against this version's fixed synthetic services; digests are integrity checks, not signatures or scholarly approval",
    }
    files += (("manifest.json", encode_json(manifest)),)
    if sum(len(raw) for _, raw in files) > MAX_BUNDLE_BYTES:
        raise ExportError("export: bundle_byte_limit")
    return ExportBundle(files)


BatchColumns = (
    "batch_id",
    "input_format",
    "input_sha256",
    "raw_source",
    "record_count",
    "valid_count",
    "rejected_count",
    "pending_count",
    "error_code",
    "recovery",
)


def verify_export(files: dict[str, bytes], *, synthetic_fixtures_only: bool = False) -> None:
    """Replay fixed services and compare every byte, including the manifest.

    Do not trust or deserialize an external manifest, even if its hashes match.
    Rehashing a tampered artifact and manifest together cannot pass replay.
    """
    require_development(synthetic_fixtures_only)
    if type(files) is not dict or set(files) != set(FILE_NAMES):
        raise ExportError("export: unexpected_files")
    if any(type(raw) is not bytes or len(raw) > MAX_FILE_BYTES for raw in files.values()):
        raise ExportError("export: invalid_file_size_or_type")
    if sum(map(len, files.values())) > MAX_BUNDLE_BYTES:
        raise ExportError("export: bundle_byte_limit")
    expected = build_export(synthetic_fixtures_only=True)
    if any(files[name] != raw for name, raw in expected.files):
        raise ExportError("export: replay_mismatch")
