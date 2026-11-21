"""Authenticated native forms; a submitted public key or URL is never accepted."""

import json
import uuid

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services
from .boundary import enabled, scope

ACTIONS = {"pd_open", "pd_select", "pd_decide", "pd_provider_event"}


def _fields(request):
    if request.method != "POST" or request.GET or request.FILES:
        raise InvalidForm("destination_form_invalid")
    action = request.POST.get("action", "")
    if action not in ACTIONS:
        raise InvalidForm("destination_form_invalid")
    required = {"action", "case_ref"}
    if action != "pd_open":
        required |= {"revision", "evidence_version", "request_key", "note", "confirmed"}
    if action == "pd_select":
        required |= {"destination", "source_selection", "expected_version"}
    if action == "pd_decide":
        required |= {"version_id", "expected_events", "command"}
    if action == "pd_provider_event":
        required |= {"version_id", "expected_events", "envelope"}
    if (
        not required <= set(request.POST)
        or set(request.POST) - required - {"csrfmiddlewaretoken"}
        or any(len(values) != 1 for _, values in request.POST.lists())
    ):
        raise InvalidForm("destination_exact_fields_required")
    return {name: request.POST[name] for name in required}


def _zero(value):
    return 0 if value == "0" else _integer(value)


def _base(request, reference):
    directory = _provider()
    actor = current_staff(request, directory, case_key=reference)
    case = Case.objects.filter(public_ref=reference).first()
    if case is None:
        raise cases.CaseConflict("destination_case_unavailable")
    return dict(
        case_id=str(case.pk),
        subject_id=actor.subject_id,
        provider=RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        ),
        synthetic_fixtures_only=True,
    )


@csrf_protect
def workspace(request):
    try:
        enabled()
        fields = _fields(request)
        base = _base(request, fields["case_ref"])
        with scope(**base) as (guard, actor):
            action = fields["action"]
            if action != "pd_open":
                audit = dict(
                    expected_revision=_integer(fields["revision"]),
                    expected_evidence_version=_integer(fields["evidence_version"]),
                    request_key=fields["request_key"],
                    note=fields["note"],
                    confirmed=fields["confirmed"] == "yes",
                )
                if action == "pd_select":
                    services.select_locked(
                        guard,
                        actor,
                        **audit,
                        destination=fields["destination"],
                        source_selection=fields["source_selection"],
                        expected_version=_zero(fields["expected_version"]),
                    )
                elif action == "pd_decide":
                    services.decide_locked(
                        guard,
                        actor,
                        **audit,
                        version_id=fields["version_id"],
                        command=fields["command"],
                        expected_events=_zero(fields["expected_events"]),
                    )
                else:
                    if not 1 <= len(fields["envelope"]) <= 12000:
                        raise InvalidForm("destination_signed_envelope_bound")
                    services.observe_locked(
                        guard,
                        actor,
                        **audit,
                        version_id=fields["version_id"],
                        envelope=json.loads(fields["envelope"]),
                        expected_events=_zero(fields["expected_events"]),
                    )
            result = services.desk_locked(guard, actor)
            return private(
                render(
                    request,
                    "publication_destinations/desk.html",
                    {
                        "result": result,
                        "request_key": str(uuid.uuid4()),
                        "message": "حُفظ سجل المحاكاة للوجهة والنسخة المحددتين."
                        if action != "pd_open"
                        else "",
                    },
                )
            )
    except IdentityUnavailable:
        return denied("destination_current_staff_required", 403)
    except cases.CaseConflict:
        return denied("destination_current_source_or_authority_changed", 409)
    except (InvalidForm, SuspiciousOperation, TypeError, ValueError):
        return denied("destination_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("destination_store_unavailable", 503)
