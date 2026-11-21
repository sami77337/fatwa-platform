"""Finite independent worker. No web-thread execution, loop, daemon or provider selection."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import OuterRef, Subquery

from apps.casework import services as cases
from apps.media_derivatives import policy, services
from apps.media_derivatives.models import DerivativeEvent, DerivativeJob
from apps.mufti_review.identity import IdentityUnavailable, MuftiIdentityProvider


class Command(BaseCommand):
    help = "Process an explicitly configured, finite private technical derivative batch."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--job")
        group.add_argument("--limit", type=int, default=1)
        parser.add_argument("--synthetic-fixtures-only", action="store_true")

    def handle(self, *args, **options):
        try:
            policy.configuration()
            provider = getattr(settings, "FATWA_MEDIA_DERIVATIVES_WORKER_DIRECTORY", None)
            if (
                not options["synthetic_fixtures_only"]
                or not 1 <= options["limit"] <= 10
                or not isinstance(provider, MuftiIdentityProvider)
                or provider is not getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
            ):
                raise cases.CaseConflict("derivative_worker_directory_required")
            rows = DerivativeJob.objects.filter(provider_id=provider.provider_id)
            if options["job"]:
                rows = rows.filter(pk=cases._uuid(options["job"]))
            else:
                last = (
                    DerivativeEvent.objects.filter(job_id=OuterRef("pk"))
                    .order_by("-sequence")
                    .values("state")[:1]
                )
                rows = rows.annotate(current_state=Subquery(last)).filter(current_state="QUEUED")
            selected = list(rows.order_by("created_at", "pk")[: options["limit"]])
            result = []
            for job in selected:
                try:
                    finished = services.run_job(
                        case_id=job.case_id,
                        subject_id=job.subject_id,
                        provider=provider,
                        job_id=job.pk,
                        synthetic_fixtures_only=True,
                    )
                    result.append(
                        {"job": str(job.pk), "state": finished["state"], "code": finished["code"]}
                    )
                except (cases.CaseConflict, IdentityUnavailable):
                    # Neither a database id nor an old request makes a grant.
                    # Omit source text, paths, identity and callback diagnostics.
                    result.append(
                        {
                            "job": str(job.pk),
                            "state": "NOT_EXECUTED",
                            "code": "CURRENT_AUTHORITY_OR_LEASE_REQUIRED",
                        }
                    )
            self.stdout.write(json.dumps({"jobs": result}, sort_keys=True))
        except (cases.CaseConflict, IdentityUnavailable, ValueError) as exc:
            raise CommandError("media_derivative_worker_unavailable") from exc
