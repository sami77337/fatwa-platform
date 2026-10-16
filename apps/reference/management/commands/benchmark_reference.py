"""Read-only measurement of the already imported, historical book-622 edition."""

import json
import statistics
from time import perf_counter

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection
from django.db.models import Count, Max, Q
from django.test.utils import CaptureQueriesContext

from apps.reference.models import ReferenceHeading
from apps.reference.normalization import normalize_title
from apps.reference.query import MAX_SOURCE_ID, InvalidQuery, Page, validate_search
from apps.reference.services import (
    CatalogUnavailable,
    HeadingNotFound,
    heading_path,
    node,
    resolve_edition,
    roots,
    search,
)
from tools.fiqh_import.book622 import ARCHIVE_SHA256, EDITION_KEY, MAPPED_CHECKSUM
from tools.fiqh_import.owner_r1 import INPUT_PINS
from tools.fiqh_import.postgres import ReadOnlySnapshotError, read_only_snapshot


def _measure(operation, repeats):
    durations, query_counts, returned_items, totals = [], [], [], []
    for _ in range(repeats):
        with CaptureQueriesContext(connection) as captured:
            started = perf_counter()
            result = operation()  # Services materialize their page/path inside this timer.
            durations.append((perf_counter() - started) * 1000)
        query_counts.append(len(captured))
        returned_items.append(len(result) if isinstance(result, list) else len(result.items))
        totals.append(len(result) if isinstance(result, list) else result.total)
    if len(set(returned_items)) != 1 or len(set(totals)) != 1:
        raise CommandError("Benchmark results changed inside the read-only snapshot")
    return {
        "latency_ms": durations,
        "median_ms": statistics.median(durations),
        "query_counts": query_counts,
        "returned_items": returned_items,
        "total_matches": totals,
    }


class Command(BaseCommand):
    help = "Measure bounded book-622 pages/citation paths in PostgreSQL READ ONLY"
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, required=True)
        parser.add_argument("--query", default="كتاب")
        parser.add_argument("--repeats", type=int, default=5)
        parser.add_argument("--expected-headings", type=int, default=11397)
        parser.add_argument("--heading-id", type=int, default=1)

    def handle(self, *args, **options):
        if not 1 <= options["repeats"] <= 20:
            raise CommandError("repeats must be 1..20")
        if options["expected_headings"] != 11397:
            raise CommandError("Historical book-622 heading count is fixed at 11397")
        if options["edition"] < 1 or not 1 <= options["heading_id"] <= MAX_SOURCE_ID:
            raise CommandError("edition/heading-id is out of range")
        try:
            validate_search(options["query"], "normalized")
            if not normalize_title(options["query"]).strip():
                raise InvalidQuery("Benchmark query must have searchable text")
            with read_only_snapshot() as database:
                edition = resolve_edition(options["edition"])
                if (
                    edition.work.source_namespace != "shamela"
                    or edition.work.source_book_id != "622"
                    or edition.edition_key != EDITION_KEY
                    or edition.source_archive_sha256 != ARCHIVE_SHA256
                    or edition.source_input_sha256 != INPUT_PINS["jsonl"]
                    or edition.ingest_checksum != MAPPED_CHECKSUM
                ):
                    raise CommandError("Edition does not identify the reviewed book-622 snapshot")
                counts = ReferenceHeading.objects.filter(edition=edition).aggregate(
                    headings=Count("pk"), roots=Count("pk", filter=Q(parent__isnull=True)),
                    max_depth=Max("depth"),
                )
                if counts != {"headings": 11397, "roots": 32, "max_depth": 5} or (
                    edition.heading_count, edition.root_count, edition.max_depth
                ) != (11397, 32, 5):
                    raise CommandError("Actual/stored totals differ from the historical snapshot")
                measurements = {
                    name: _measure(operation, options["repeats"])
                    for name, operation in {
                        "roots": lambda: roots(edition, Page(30)),
                        "normalized_search": lambda: search(
                            edition, options["query"], "normalized", Page(30)
                        ),
                        "citation_path": lambda: heading_path(
                            edition, node(edition, options["heading_id"])
                        ),
                    }.items()
                }
                report = {
                    "kind": "SOURCE_BOOK_TOC_NOT_FATWAS",
                    "database_import": "NOT_RUN",
                    "transaction": "REPEATABLE READ / READ ONLY",
                    "postgres_version": database.pg_version,
                    "edition_id": edition.pk,
                    "actual_counts": counts,
                    "actual_heading_count": counts["headings"],
                    "source_archive_sha256": edition.source_archive_sha256,
                    "source_input_sha256": edition.source_input_sha256,
                    "mapped_checksum": edition.ingest_checksum,
                    "input_name": edition.input_name,
                    "source_fidelity": "NOT_AUDITED",
                    "source_fidelity_command": "audit_book622",
                    "query": options["query"],
                    "heading_id": options["heading_id"],
                    "page_limit": 30,
                    "citation_path_limit": 5,
                    "measurement_scope": (
                        "Materialized ORM page/path calls only; page count queries included; "
                        "snapshot checks, source validation, connection setup and HTTP excluded"
                    ),
                    "results": measurements,
                    "deployment_status": "NOT_DEPLOYED",
                    "gates": "GATES_HOLD_PHASE01_BLOCKED",
                }
        except (HeadingNotFound, InvalidQuery, CatalogUnavailable) as error:
            raise CommandError(str(error)) from error
        except (DatabaseError, ReadOnlySnapshotError) as error:
            raise CommandError(
                "Read-only PostgreSQL benchmark unavailable; no changes made"
            ) from error
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
