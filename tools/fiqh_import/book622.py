"""Pinned owner ZIP -> S1 validation -> S0 records. Never executes archive code."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path

from apps.reference.records import CatalogSpec, HeadingRecord, PreparedCatalog, prepare_catalog
from tools.fiqh_import import ingest, load_manifest
from tools.fiqh_import.ingest import IngestError

ARCHIVE_SHA256 = "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce"
PREFIX = "FATWA_622_FIQH_COMPLETE/"
INPUT_MEMBER = PREFIX + "622_الفهرس_كامل_11397.jsonl"
ORIGINAL_MEMBER = PREFIX + "622_العناوين_الأصلية_ID_title.csv"
ORIGINAL_SHA256 = "13edc878f0b81d178c104bc976c4fe0d3970d8a1ef8bae26d6101f22ebbcd1a9"
MANIFEST = Path(__file__).resolve().parents[2] / "docs/data-ingest/owner-622-r1-jsonl.manifest.json"
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024


def validate_book622(archive_path: str | Path) -> tuple[PreparedCatalog, dict]:
    """Validate exact ZIP/member pins and every original title before ORM access."""
    archive_path = Path(archive_path)
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise IngestError("Owner ZIP exceeds the input limit")
    raw_archive = archive_path.read_bytes()
    if hashlib.sha256(raw_archive).hexdigest() != ARCHIVE_SHA256:
        raise IngestError("Owner ZIP SHA256 does not match the reviewed source")
    manifest = load_manifest(MANIFEST)
    with zipfile.ZipFile(io.BytesIO(raw_archive)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise IngestError("Duplicate ZIP member identity")
        members = {}
        for name in (INPUT_MEMBER, ORIGINAL_MEMBER):
            info = archive.getinfo(name)
            if info.file_size > MAX_MEMBER_BYTES or info.flag_bits & 1:
                raise IngestError("Oversized or encrypted source member")
            members[name] = archive.read(name)
    original_raw = members[ORIGINAL_MEMBER]
    if hashlib.sha256(original_raw).hexdigest() != ORIGINAL_SHA256:
        raise IngestError("Original-title CSV SHA256 mismatch")
    originals = list(csv.DictReader(io.StringIO(original_raw.decode("utf-8-sig"), newline="")))
    original_titles = {row["title_id"]: row["original_title"] for row in originals}
    if len(originals) != 11397 or len(original_titles) != 11397:
        raise IngestError("Original ID/title index is incomplete or contains duplicates")
    # A temporary member is required by S1's existing file API; no export is retained.
    with tempfile.TemporaryDirectory(prefix="fatwa-622-") as scratch:
        input_path = Path(scratch) / Path(INPUT_MEMBER).name
        input_path.write_bytes(members[INPUT_MEMBER])
        validated = ingest(input_path, manifest, profile="real-622", input_adapter="owner-622-r1")
    if not validated.report["valid"] or validated.output_bytes is None:
        raise IngestError("S1 did not produce validated output")
    if hashlib.sha256(validated.output_bytes).hexdigest() != validated.report["output_sha256"]:
        raise IngestError("S1 output checksum mismatch")
    rows = [json.loads(line) for line in validated.output_bytes.splitlines()]
    if {row["source_id"]: row["title"] for row in rows} != original_titles:
        raise IngestError("S1 output differs from the independent original ID/title index")
    records = tuple(
        HeadingRecord(
            source_id=row["source_metadata"]["lucene_title_key"],
            source_row_id=int(row["source_id"]),
            parent_source_row_id=int(row["parent_id"]) if row["parent_id"] is not None else None,
            source_order=row["input_record"],
            position=row["sibling_order"],
            depth=row["depth"],
            source_page_id=row["source_metadata"]["source_page_id"],
            source_part=str(row["source_part"]),
            source_page_number=row["page"],
            title_original=row["title"],
            source_entry_number=row["source_metadata"]["source_entry_number"],
        )
        for row in rows
    )
    spec = CatalogSpec(
        source_namespace="shamela",
        source_book_id="622",
        work_title="كشاف القناع عن متن الإقناع",
        madhhab="حنبلي",
        edition_key="622-moj-owner-r1-20261011",
        edition_title=manifest.edition,
        publisher="وزارة العدل السعودية",
        source_archive_sha256=ARCHIVE_SHA256,
        source_input_sha256=validated.report["input_sha256"],
        input_name=Path(INPUT_MEMBER).name,
        expected_rows=11397,
        expected_roots=32,
        expected_max_depth=5,
    )
    prepared = prepare_catalog(spec, records)
    return prepared, {
        **validated.report,
        "source_archive_sha256": ARCHIVE_SHA256,
        "input_member": INPUT_MEMBER,
        "original_titles_sha256": ORIGINAL_SHA256,
        "exact_original_id_title_matches": len(original_titles),
        "mapped_checksum": prepared.checksum,
        "database_import": "NOT_RUN",
    }
