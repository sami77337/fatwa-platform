"""Native case-scoped future edition choice, cancellation and due-worker review."""

import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError, transaction
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services

BASE = {"action", "case_ref"}
SHAPES = {
    "ps_open": BASE,
    "ps_schedule": BASE
    | {
        "edition_id",
        "scheduled_at",
        "target",
        "revision",
        "evidence_version",
        "request_key",
        "reason",
        "confirmed",
    },
    "ps_cancel": BASE | {"schedule_id", "confirmed"},
    "ps_run": BASE | {"schedule_id", "confirmed"},
}
ACTIONS = frozenset(SHAPES)


@csrf_protect
def workspace(request):
    try:
        services.enabled()
        if request.method != "POST" or request.POST.get("action") not in ACTIONS or request.FILES:
            raise InvalidForm("schedule_form_invalid")
        values = _form(request, SHAPES[request.POST["action"]])
        directory = _provider()
        actor = current_staff(request, directory, case_key=values["case_ref"])
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        case = Case.objects.filter(public_ref=values["case_ref"]).first()
        if case is None:
            return denied("schedule_unavailable", 404)
        common = dict(
            case_id=case.pk,
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        with synthetic_queue_atomic(), services.boundary(**common):
            if values["action"] != "ps_open" and values["confirmed"] != "yes":
                raise InvalidForm("schedule_confirmation_required")
            if values["action"] == "ps_schedule":
                when = datetime.fromisoformat(values["scheduled_at"])
                if when.tzinfo is not None:
                    raise InvalidForm("schedule_local_time_required")
                when = when.replace(tzinfo=ZoneInfo("Asia/Amman")).astimezone(dt_timezone.utc)
                services.prepare(
                    **common,
                    edition_id=values["edition_id"],
                    scheduled_at=when,
                    target=values["target"],
                    expected_revision=_integer(values["revision"]),
                    expected_evidence_version=_integer(values["evidence_version"]),
                    request_key=values["request_key"],
                    reason=values["reason"],
                    confirmed=True,
                )
            elif values["action"] == "ps_cancel":
                services.cancel(**common, schedule_id=values["schedule_id"], confirmed=True)
            elif values["action"] == "ps_run":
                services.run_for_staff(**common, schedule_id=values["schedule_id"], confirmed=True)
            data = services.desk(**common)
            response = render(
                request,
                "publication_schedules/desk.html",
                {
                    "desk": data,
                    "request_key": str(uuid.uuid4()),
                    "suggested_time": (timezone.now() + timedelta(minutes=5))
                    .astimezone(ZoneInfo("Asia/Amman"))
                    .strftime("%Y-%m-%dT%H:%M"),
                },
            )
            if response.status_code >= 400:
                transaction.set_rollback(True)
            return private(response)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError):
        return denied("schedule_form_invalid", 400)
    except IdentityUnavailable:
        return denied("schedule_identity_required", 403)
    except cases.CaseConflict:
        return denied("schedule_unavailable_or_changed", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("schedule_store_unavailable", 503)
