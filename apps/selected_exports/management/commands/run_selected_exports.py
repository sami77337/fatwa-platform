"""Resume a bounded queued job outside a browser, using the configured directory."""

import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.casework.services import CaseConflict
from apps.mufti_review.identity import IdentityUnavailable
from apps.selected_exports import services


class Command(BaseCommand):
    help = "Run one already queued private export; never infer a role or export grant."

    def add_arguments(self, parser):
        parser.add_argument("--case-id", required=True)
        parser.add_argument("--job-id", required=True)
        parser.add_argument("--subject", required=True)
        parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)

    def handle(self, *args, **options):
        try:
            result = services.run_job(
                case_id=options["case_id"],
                job_id=options["job_id"],
                subject_id=options["subject"],
                provider=getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
                request_key=uuid.uuid4(),
                synthetic_fixtures_only=options["synthetic_fixtures_only"],
            )
        except (CaseConflict, IdentityUnavailable) as exc:
            raise CommandError(
                "The queued export is unavailable under current authorization."
            ) from exc
        self.stdout.write(
            f"state={result['state']} included={result['completed']} requested={result['requested']}"
        )
