"""Full source-vs-database audit of the existing edition; no import/repair option."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.db.models import F

from apps.reference.models import ReferenceEdition, ReferenceHeading
from apps.reference.query import MAX_SOURCE_ID
from apps.reference.records import MAX_ROWS, InvalidCatalog
from apps.reference.services import CatalogUnavailable, HeadingNotFound, heading_path, node
from tools.fiqh_import.audit import ROW_FIELDS, audit_catalog
from tools.fiqh_import.book622 import validate_book622
from tools.fiqh_import.citation_audit import audit_citation_metadata
from tools.fiqh_import.ingest import IngestError
from tools.fiqh_import.postgres import ReadOnlySnapshotError, read_only_snapshot


class Command(BaseCommand):
    help = "Compare every historical book-622 field in a PostgreSQL READ ONLY snapshot"
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--archive", required=True)
        parser.add_argument("--edition", type=int, required=True)
        parser.add_argument("--max-issues", type=int, default=20)
        parser.add_argument("--heading-id", type=int, help="Optional single bounded citation")

    def handle(self, *args, **options):
        if not 1 <= options["max_issues"] <= 100:
            raise CommandError("max-issues must be 1..100")
        if options["edition"] < 1:
            raise CommandError("edition must be positive")
        ident = options["heading_id"]
        if ident is not None and not 1 <= ident <= MAX_SOURCE_ID:
            raise CommandError("heading-id is out of range")
        try:
            # Verify the trusted ZIP completely before opening a database connection.
            prepared, source = validate_book622(options["archive"])
            with read_only_snapshot() as database:
                edition = ReferenceEdition.objects.select_related("work").filter(
                    pk=options["edition"]
                ).first()
                if edition is None:
                    raise CommandError("Unknown edition; no snapshot created or repaired")
                metadata = {
                    "edition_id": edition.pk,
                    "source_namespace": edition.work.source_namespace,
                    "source_book_id": edition.work.source_book_id,
                    "work_title": edition.work.title_original,
                    "madhhab": edition.work.madhhab,
                    "edition_key": edition.edition_key,
                    "edition_title": edition.title,
                    "publisher": edition.publisher,
                    "source_archive_sha256": edition.source_archive_sha256,
                    "source_input_sha256": edition.source_input_sha256,
                    "input_name": edition.input_name,
                    "ingest_checksum": edition.ingest_checksum,
                    "heading_count": edition.heading_count,
                    "root_count": edition.root_count,
                    "max_depth": edition.max_depth,
                }
                rows = ReferenceHeading.objects.filter(edition=edition).annotate(
                    parent_source_row_id=F("parent__source_row_id"),
                    parent_edition_id=F("parent__edition_id"),
                ).order_by("source_row_id", "pk").values(*ROW_FIELDS)[:MAX_ROWS + 1]
                report = audit_catalog(
                    prepared, metadata, rows.iterator(chunk_size=1000),
                    max_issues=options["max_issues"],
                )
                report.update({
                    "citation_metadata": audit_citation_metadata(prepared),
                    "source_validation": source,
                    "postgres_version": database.pg_version,
                    "transaction": "REPEATABLE READ / READ ONLY",
                })
                if not report["valid"]:
                    self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
                    raise CommandError("Source/database mismatch; no changes made")
                if ident is not None:
                    heading = node(edition, ident)
                    ancestors = heading_path(edition, heading)
                    report["citation"] = {
                        "kind": "SOURCE_BOOK_TOC_NOT_FATWAS",
                        "work_title": edition.work.title_original,
                        "edition_title": edition.title,
                        "edition_key": edition.edition_key,
                        "source_namespace": edition.work.source_namespace,
                        "source_book_id": edition.work.source_book_id,
                        "source_archive_sha256": edition.source_archive_sha256,
                        "source_input_sha256": edition.source_input_sha256,
                        "source_id": heading.source_id,
                        "heading_id": heading.source_row_id,
                        "title": heading.title_original,
                        "part": heading.source_part,
                        "page": heading.source_page_number,
                        "page_id": heading.source_page_id,
                        "path": [{"id": row["id"], "title": row["title"]} for row in ancestors],
                    }
        except (DatabaseError, ReadOnlySnapshotError) as error:
            raise CommandError("Read-only PostgreSQL audit unavailable; no changes made") from error
        except (IngestError, InvalidCatalog, OSError, ValueError, KeyError) as error:
            raise CommandError(
                "Source verification failed; no changes made: " + str(error)
            ) from error
        except (HeadingNotFound, CatalogUnavailable) as error:
            raise CommandError("Bounded citation unavailable: " + str(error)) from error
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
