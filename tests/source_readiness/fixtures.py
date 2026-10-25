"""Generate deterministic synthetic bytes; never read owner evidence."""

import io
import json
import zipfile
from dataclasses import asdict
from hashlib import sha256

from apps.reference.records import CatalogSpec, HeadingRecord, prepare_catalog


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def bundle():
    rows = [
        HeadingRecord("synthetic:1", 1, None, 1, 1, 1, 101, "الأول", 3, "  كِتابٌ اصطناعي  "),
        HeadingRecord("synthetic:2", 2, 1, 2, 1, 2, 102, "الأول", 4, "بَابٌ تجريبي e\u0301"),
    ]
    identity = dict(
        source_namespace="synthetic-readiness",
        source_book_id="622",
        work_title="مرجع اصطناعي للاختبار",
        madhhab="اختبار",
        edition_key="synthetic-readiness-v1",
        edition_title="طبعة اختبار",
        publisher="اختبار محلي",
        input_name="synthetic-rows.json",
    )
    raw = encode(
        dict(
            schema="fatwa.source-readiness.rows.v1",
            identity=identity,
            records=[asdict(row) for row in rows],
        )
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        entry = zipfile.ZipInfo(identity["input_name"], date_time=(2026, 1, 1, 0, 0, 0))
        archive.writestr(entry, raw)
    archive = stream.getvalue()
    spec = CatalogSpec(
        **identity,
        source_input_sha256=sha256(raw).hexdigest(),
        source_archive_sha256=sha256(archive).hexdigest(),
        expected_rows=2,
        expected_roots=1,
        expected_max_depth=2,
    )
    manifest = dict(
        schema="fatwa.source-readiness.manifest.v1",
        dataset_id="generated-synthetic-readiness-v1",
        source_kind="synthetic",
        edition_id=7001,
        spec=asdict(spec),
        catalog_checksum=prepare_catalog(spec, rows).checksum,
    )
    snapshot = dict(
        schema="fatwa.source-readiness.snapshot.v1",
        edition_id=7001,
        spec=asdict(spec),
        records=[asdict(row) for row in rows],
    )
    return manifest, snapshot, raw, archive
