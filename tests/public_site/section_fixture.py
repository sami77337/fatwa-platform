"""public-source-sections-v1: synthetic roots, descendants to depth five and peers."""

from apps.reference.ingest import ingest_catalog
from apps.reference.records import CatalogSpec, HeadingRecord


def seed_sections():
    spec = CatalogSpec(
        source_namespace="synthetic",
        source_book_id="public-source-sections-v1",
        work_title="مرجع أبواب اصطناعي",
        madhhab="اختبار",
        edition_key="sections-v1",
        edition_title="طبعة اختبار",
        publisher="ناشر اصطناعي",
        source_archive_sha256="d" * 64,
        source_input_sha256="e" * 64,
        input_name="public-source-sections-v1.jsonl",
        expected_rows=67,
        expected_roots=2,
        expected_max_depth=5,
    )
    definitions = [(1, None, 1, 1, "باب أول اصطناعي")]
    definitions += [(n, 1, 2, n - 1, f"عنوان مشترك {n:03d}") for n in range(2, 63)]
    definitions += [
        (63, 62, 3, 1, "فرع ثالث"),
        (64, 63, 4, 1, "فرع رابع"),
        (65, 64, 5, 1, "فرع خامس"),
        (100, None, 1, 2, "باب ثان اصطناعي"),
        (101, 100, 2, 1, "عنوان مشترك خارج الباب"),
    ]
    rows = tuple(
        HeadingRecord(
            f"section-{ident}",
            ident,
            parent,
            order,
            position,
            depth,
            1000 + ident,
            "جزء اصطناعي",
            ident,
            title,
        )
        for order, (ident, parent, depth, position, title) in enumerate(definitions, 1)
    )
    preview = ingest_catalog(spec, rows)
    return ingest_catalog(spec, rows, dry_run=False, expected_checksum=preview.checksum).edition_id
