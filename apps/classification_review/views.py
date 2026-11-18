"""Native, CSRF-protected staff actions; trusted identity comes from RequestDirectory."""

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import editorial_views, services

ACTIONS = editorial_views.ACTIONS | {
    "classification_desk",
    "classification_history",
    "classification_propose",
    "classification_approve",
    "classification_reject",
    "classification_withdraw",
}


@sensitive_post_parameters("label", "reason", "note")
@csrf_protect
def workspace(request):
    if request.POST.get("action") in editorial_views.ACTIONS:
        return editorial_views.workspace(request)
    try:
        services._enabled()
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("classification_form_invalid")
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        action = request.POST.get("action")
        required = {"action", "publication_id"}
        if action == "classification_propose":
            required |= {"knowledge_id", "label", "reason", "replaces_id"}
        elif action in {
            "classification_approve",
            "classification_reject",
            "classification_withdraw",
        }:
            required |= {"revision_id", "note", "confirm"}
        fields = _form(request, required)
        if request.FILES:
            raise InvalidForm("classification_form_invalid")
        common = dict(
            publication_id=fields["publication_id"],
            subject_id=identity.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        result = None
        if action == "classification_propose":
            result = services.propose(
                **common,
                knowledge_id=fields["knowledge_id"],
                label=fields["label"],
                reason=fields["reason"],
                replaces_id=fields["replaces_id"] or None,
            )
        elif action in {
            "classification_approve",
            "classification_reject",
            "classification_withdraw",
        }:
            result = services.act(
                **common,
                revision_id=fields["revision_id"],
                note=fields["note"],
                confirmed=fields["confirm"] == "yes",
                action=action.removeprefix("classification_").upper(),
            )
        context = services.desk(
            **common, history=action in {"classification_history", "classification_withdraw"}
        )
        request.classification_authorized_case_ref = context["public_ref"]
        context["result"] = result
        return private(render(request, "classification_review/desk.html", context))
    except (InvalidForm, SuspiciousOperation):
        return denied("classification_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("classification_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("classification_store_unavailable", 503)
