"""Bounded ORM reads on an explicit alias, in a fresh PostgreSQL snapshot."""

from dataclasses import fields

from apps.reference.records import HeadingRecord, PreparedCatalog

from .services import (
    CatalogReadUnavailable,
    CatalogRows,
    edition_fields,
    validated_pin,
    work_fields,
)


class DjangoConsistencyReader:
    def __init__(self, *, using: str):
        if type(using) is not str or not using or len(using) > 100:
            raise ValueError("Explicit database alias required")
        self.using = using

    def read(self, pin: PreparedCatalog, edition_id: int) -> CatalogRows:
        # Validate before importing models or resolving any database connection.
        pin = validated_pin(pin, edition_id)
        from django.core.exceptions import AppRegistryNotReady, ImproperlyConfigured
        from django.db import DatabaseError, connections, transaction
        from django.utils.connection import ConnectionDoesNotExist

        try:
            from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork

            connection = connections[self.using]
            if (
                connection.vendor != "postgresql"
                or connection.in_atomic_block
                or not connection.get_autocommit()
            ):
                raise CatalogReadUnavailable("Independent PostgreSQL transaction required")
            with transaction.atomic(using=self.using, durable=True):
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    cursor.execute("SET LOCAL statement_timeout = '3000ms'")
                    cursor.execute("SET LOCAL lock_timeout = '1000ms'")
                works = tuple(
                    ReferenceWork.objects.using(self.using)
                    .filter(
                        source_namespace=pin.spec.source_namespace,
                        source_book_id=pin.spec.source_book_id,
                    )
                    .order_by("pk")
                    .values("id", *work_fields(pin))[:2]
                )
                editions = ()
                headings = ()
                if len(works) == 1:
                    editions = tuple(
                        ReferenceEdition.objects.using(self.using)
                        .filter(
                            work_id=works[0]["id"],
                            edition_key=pin.spec.edition_key,
                        )
                        .order_by("pk")
                        .values("id", "work_id", *edition_fields(pin))[:2]
                    )
                # Never use a discovered edition as a replacement for the explicit pin.
                if len(editions) == 1 and editions[0]["id"] == edition_id:
                    columns = [
                        f.name for f in fields(HeadingRecord) if f.name != "parent_source_row_id"
                    ]
                    headings = tuple(
                        ReferenceHeading.objects.using(self.using)
                        .filter(
                            edition_id=edition_id,
                        )
                        .order_by("source_order", "source_row_id")
                        .values(
                            "id",
                            "edition_id",
                            "parent_id",
                            "parent__source_row_id",
                            "parent__edition_id",
                            "title_normalized",
                            *columns,
                        )[: len(pin.records) + 1]
                    )
                result = CatalogRows(works, editions, headings)
            # Transaction exit must succeed before a complete snapshot is returned.
            return result
        except (
            DatabaseError,
            AppRegistryNotReady,
            ImproperlyConfigured,
            ConnectionDoesNotExist,
        ) as error:
            raise CatalogReadUnavailable("Catalog read unavailable") from error
