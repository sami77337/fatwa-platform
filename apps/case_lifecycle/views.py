"""Native RTL lifecycle forms on the existing guarded staff endpoint."""

import uuid
from functools import wraps

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError, transaction
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

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
MUTATION = BASE | {"revision", "evidence_version", "version", "command_id", "reason", "confirm"}
SHAPES = {
    "lc_open": BASE,
    "lc_inbox": {"action"},
    "lc_filter": {"action", "state", "query"},
    "lc_close": MUTATION | {"without_delivery"},
    "lc_reopen": MUTATION,
    "lc_archive": MUTATION,
    "lc_restore": MUTATION,
}
ACTIONS = frozenset(SHAPES)


def _render(request, result, template, *, notice=""):
    guard = result.pop("_guard")
    response = render(
        request,
        template,
        {
            "lifecycle": result,
            "command_id": str(uuid.uuid4()),
            "states": services.STATE_LABELS.items(),
            "notice": notice,
        },
    )
    guard.check()
    return private(response)


def _transaction(function):
    @wraps(function)
    def wrapped(request):
        try:
            services._enabled()
            cases._guard(True)
            with synthetic_queue_atomic():
                response = function(request)
                if response.status_code >= 400:
                    transaction.set_rollback(True)
                return response
        except cases.CaseConflict:
            return denied("lifecycle_unavailable_or_changed", 409)
        except (DatabaseError, SyntheticWriteDenied):
            return denied("lifecycle_store_unavailable", 503)

    return wrapped


@sensitive_post_parameters("reason")
@csrf_protect
@_transaction
def workspace(request):
    try:
        action = request.POST.get("action")
        if request.method != "POST" or action not in ACTIONS or request.FILES:
            raise InvalidForm("lifecycle_form_invalid")
        shape = set(SHAPES[action])
        # A native unchecked checkbox sends no field. Missing is false, never permission.
        if action == "lc_close" and "without_delivery" not in request.POST:
            shape.remove("without_delivery")
        values = _form(request, shape)
        directory = _provider()
        actor = current_staff(request, directory, case_key=values.get("case_ref"))
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        if action in {"lc_inbox", "lc_filter"}:
            options = (
                {key: values[key] for key in ("state", "query")} if action == "lc_filter" else {}
            )
            result = services.inbox(**common, **options)
            return _render(request, result, "case_lifecycle/inbox.html")
        selected = Case.objects.filter(public_ref=values["case_ref"]).first()
        if selected is None:
            return denied("lifecycle_case_unavailable", 404)
        common["case_id"] = selected.pk
        notice = ""
        if action != "lc_open":
            if values["confirm"] != "yes" or values.get("without_delivery", "no") not in {
                "yes",
                "no",
            }:
                raise InvalidForm("lifecycle_confirmation_required")
            version = 0 if values["version"] == "0" else _integer(values["version"])
            services.command(
                **common,
                action=action.removeprefix("lc_").upper(),
                reason=values["reason"],
                expected_revision=_integer(values["revision"]),
                expected_evidence_version=_integer(values["evidence_version"]),
                expected_version=version,
                command_id=values["command_id"],
                without_delivery=values.get("without_delivery", "no") == "yes",
            )
            notice = "حُفظ الإجراء في سجل دورة الحياة. الأصل والجواب وسجلات التوصيل والنشر باقية."
        return _render(request, services.desk(**common), "case_lifecycle/desk.html", notice=notice)
    except (InvalidForm, SuspiciousOperation, TypeError):
        return denied("lifecycle_form_invalid", 400)
    except IdentityUnavailable:
        return denied("lifecycle_identity_unavailable", 403)


def dispatch(request):
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return workspace(request)
    from apps.requester_team_journey.views import staff

    return staff(request)
