"""Synthetic public-search-pagination-v1; no owner corpus or private case data."""

from apps.reference.ingest import ingest_catalog
from apps.reference.records import CatalogSpec, HeadingRecord


def seed_catalog():
    spec = CatalogSpec(
        source_namespace="synthetic",
        source_book_id="public-search-pagination-v1",
        work_title="مرجع البحث الاصطناعي",
        madhhab="اختبار",
        edition_key="public-search-pagination-v1",
        edition_title="طبعة اختبار",
        publisher="ناشر اصطناعي",
        source_archive_sha256="d" * 64,
        source_input_sha256="e" * 64,
        input_name="public-search-pagination-v1.jsonl",
        expected_rows=62,
        expected_roots=1,
        expected_max_depth=2,
    )
    rows = (
        HeadingRecord("root", 1, None, 1, 1, 1, 1001, "جزء اصطناعي", 1, "باب اصطناعي"),
    ) + tuple(
        HeadingRecord(
            f"search-{n}", n, 1, n, n - 1, 2, 1000 + n, "جزء اصطناعي", n, f"عُنْوَانٌ اصطناعي {n:03d}"
        )
        for n in range(2, 63)
    )
    preview = ingest_catalog(spec, rows)
    return ingest_catalog(spec, rows, dry_run=False, expected_checksum=preview.checksum).edition_id
