"""Explicit PostgreSQL reader; no connection or source discovery at import time."""

from contextlib import contextmanager
from dataclasses import fields

from apps.reference.records import MAX_ROWS, CatalogSpec, HeadingRecord, prepare_catalog
from apps.reference_links.django_adapter import DjangoCatalog
from apps.reference_links.resolution import CatalogReadError

from .services import CatalogSnapshot


class DjangoNavigationReader:
    @contextmanager
    def snapshot(self, edition_id: int):
        from django.db import DatabaseError, connection, router, transaction

        from apps.reference import services
        from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork

        if type(edition_id) is not int or not 1 <= edition_id <= 2**63 - 1:
            raise CatalogReadError("Explicit edition required")
        # DjangoCatalog uses the default alias. Never pretend a transaction on a
        # different connection protects its evidence reads.
        if connection.vendor != "postgresql" or any(
            router.db_for_read(model) != "default"
            for model in (ReferenceEdition, ReferenceHeading, ReferenceWork)
        ):
            raise CatalogReadError("Default PostgreSQL reader required")
        try:
            if connection.in_atomic_block or not connection.get_autocommit():
                raise CatalogReadError("An independent read transaction is required")
            with transaction.atomic(durable=True):
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                edition = services.resolve_edition(edition_id)
                spec = CatalogSpec(
                    source_namespace=edition.work.source_namespace,
                    source_book_id=edition.work.source_book_id,
                    work_title=edition.work.title_original,
                    madhhab=edition.work.madhhab,
                    edition_key=edition.edition_key,
                    edition_title=edition.title,
                    publisher=edition.publisher,
                    source_archive_sha256=edition.source_archive_sha256,
                    source_input_sha256=edition.source_input_sha256,
                    input_name=edition.input_name,
                    expected_rows=edition.heading_count,
                    expected_roots=edition.root_count,
                    expected_max_depth=edition.max_depth,
                )
                if not 1 <= spec.expected_rows <= MAX_ROWS:
                    raise CatalogReadError("Bounded topology required")
                columns = [
                    f.name for f in fields(HeadingRecord) if f.name != "parent_source_row_id"
                ]
                rows = list(
                    ReferenceHeading.objects.filter(edition_id=edition_id)
                    .order_by("source_order", "source_row_id")
                    .values(*columns, "parent_id", "parent__source_row_id", "parent__edition_id")[
                        : spec.expected_rows + 1
                    ]
                )
                records = []
                for row in rows:
                    parent_pk = row.pop("parent_id")
                    parent_edition = row.pop("parent__edition_id")
                    parent_row = row.pop("parent__source_row_id")
                    if parent_pk is not None and (
                        parent_edition != edition_id or parent_row is None
                    ):
                        raise CatalogReadError("Foreign or missing parent")
                    records.append(HeadingRecord(**row, parent_source_row_id=parent_row))
                prepared = prepare_catalog(spec, records)
                if prepared.checksum != edition.ingest_checksum:
                    raise CatalogReadError("Stored catalog checksum mismatch")
                yield CatalogSnapshot(edition_id, prepared, DjangoCatalog())
        except (DatabaseError, services.HeadingNotFound, services.CatalogUnavailable) as error:
            raise CatalogReadError("Catalog read unavailable") from error
