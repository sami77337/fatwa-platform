"""Read-only measurement of an already imported, source-pinned development edition."""
import json
import statistics
from time import perf_counter

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.reference.models import ReferenceHeading
from apps.reference.query import InvalidQuery, Page
from apps.reference.services import HeadingNotFound, resolve_edition, roots, search


class Command(BaseCommand):
    help = "Measure actual query counts/latency; never imports or publishes data"

    def add_arguments(self, parser):
        parser.add_argument("--edition", type=int, required=True)
        parser.add_argument("--query", default="كتاب")
        parser.add_argument("--repeats", type=int, default=5)
        parser.add_argument("--expected-headings", type=int, default=11397)

    def handle(self, *args, **options):
        if not 1 <= options["repeats"] <= 20:
            raise CommandError("repeats must be 1..20")
        if connection.vendor != "postgresql" or not 170000 <= connection.pg_version < 190000:
            raise CommandError("Requires real PostgreSQL 17/18")
        try:
            edition = resolve_edition(options["edition"])
            count = ReferenceHeading.objects.filter(edition=edition).count()
            if count != options["expected_headings"] or count != edition.heading_count:
                raise CommandError("Actual heading count does not match the expected snapshot")
            measurements = {}
            for name, operation in {
                "roots": lambda: roots(edition, Page(30)),
                "normalized_search": lambda: search(edition, options["query"], "normalized", Page(30)),
            }.items():
                durations, query_counts = [], []
                for _ in range(options["repeats"]):
                    with CaptureQueriesContext(connection) as captured:
                        started = perf_counter()
                        operation()
                        durations.append((perf_counter() - started) * 1000)
                    query_counts.append(len(captured))
                measurements[name] = {
                    "latency_ms": durations, "median_ms": statistics.median(durations),
                    "query_counts": query_counts,
                }
        except (HeadingNotFound, InvalidQuery) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps({
            "kind": "SOURCE_BOOK_TOC_NOT_FATWAS", "postgres_version": connection.pg_version,
            "edition_id": edition.pk, "actual_heading_count": count,
            "source_archive_sha256": edition.source_archive_sha256,
            "source_input_sha256": edition.source_input_sha256, "input_name": edition.input_name,
            "measurement_scope": "ORM services; includes count and materialization; excludes HTTP rendering",
            "results": measurements,
        }, ensure_ascii=False, indent=2))
