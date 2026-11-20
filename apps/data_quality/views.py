"""Native scoped diagnostics; no repair or scholarly decision action."""

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services

ACTIONS = {"quality_open", "quality_case"}


@csrf_protect
def workspace(request):
    return _handle(request, index=False)


@csrf_protect
def index(request):
    return _handle(request, index=True)


def _handle(request, *, index):
    try:
        services.enabled()
        if index:
            if request.method not in {"GET", "HEAD"} or request.GET or request.FILES:
                raise InvalidForm("quality_form_invalid")
            fields, action = {"page": "1"}, "quality_open"
        else:
            action = request.POST.get("action")
            if request.method != "POST" or action not in ACTIONS or request.FILES:
                raise InvalidForm("quality_form_invalid")
            fields = _form(
                request, {"action", "page"} if action == "quality_open" else {"action", "case_ref"}
            )
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        with services.projection(
            subject_id=identity.subject_id,
            provider=provider,
            page=_integer(fields["page"]) if action == "quality_open" else 1,
            case_ref=fields.get("case_ref"),
            synthetic_fixtures_only=True,
        ) as result:
            return private(render(request, "data_quality/desk.html", {"quality": result}))
    except (InvalidForm, SuspiciousOperation):
        return denied("quality_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("quality_unavailable", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("quality_store_unavailable", 503)
