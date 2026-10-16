"""Local-only reviewed source import. No source or synthetic seeding on web startup."""

import json
from dataclasses import asdict

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.reference.ingest import ingest_catalog
from apps.reference.records import InvalidCatalog
from tools.fiqh_import.book622 import validate_book622
from tools.fiqh_import.ingest import IngestError


class Command(BaseCommand):
    help = "Verify original book-622 ZIP, preview S0 import, then explicitly apply by checksum"
    # Source validation can run without connecting to PostgreSQL.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--archive", required=True)
        parser.add_argument("--validate-only", action="store_true")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-checksum")

    def handle(self, *args, **options):
        if options["validate_only"] and options["apply"]:
            raise CommandError("--validate-only cannot be combined with --apply")
        if bool(options["apply"]) != bool(options["expected_checksum"]):
            raise CommandError("--apply requires --expected-checksum from a successful preview")
        self.check()
        try:
            prepared, report = validate_book622(options["archive"])
            if not options["validate_only"]:
                self.check(databases=["default"])
                result = ingest_catalog(
                    prepared.spec,
                    prepared.records,
                    dry_run=not options["apply"],
                    expected_checksum=options["expected_checksum"],
                )
                report["persistence"] = asdict(result)
                report["database_import"] = (
                    "PREVIEW_ONLY"
                    if result.dry_run
                    else "UNCHANGED"
                    if result.unchanged
                    else "IMPORTED"
                )
        except DatabaseError as error:
            raise CommandError(
                "Database unavailable or snapshot rejected. Check the local PostgreSQL connection "
                "and migrations; no partial snapshot is accepted."
            ) from error
        except (IngestError, InvalidCatalog, OSError, ValueError, KeyError) as error:
            raise CommandError(
                "Source validation/import failed; no partial snapshot is accepted: " + str(error)
            ) from error
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
