"""Native POST navigation on the existing loopback/auth/CSRF guarded staff route."""

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services

ACTIONS = {
    "knowledge_browse",
    "knowledge_preview",
    "knowledge_history",
    "knowledge_open",
    "knowledge_desk",
    "knowledge_propose",
    "knowledge_approve",
    "knowledge_withdraw",
}


@sensitive_post_parameters("reason", "query")
@csrf_protect
def workspace(request):
    try:
        services._enabled()
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("knowledge_form_invalid")
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        action = request.POST.get("action")
        required = {"action", "publication_id", "query"}
        if action in {"knowledge_open", "knowledge_preview"}:
            required |= {"revision_id"}
        elif action == "knowledge_propose":
            required |= {"kind", "target_id", "reason", "replaces_id"}
        elif action in {"knowledge_approve", "knowledge_withdraw"}:
            required |= {"revision_id", "confirm"}
        fields = _form(request, required)
        if request.FILES:
            raise InvalidForm("knowledge_form_invalid")
        query = fields["query"]
        cases._text(query, optional=True)
        if len(query) > 80:
            raise InvalidForm("knowledge_query_too_long")
        common = dict(
            publication_id=fields["publication_id"],
            subject_id=identity.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        get_token(request)
        context = {"query": query, "publication_id": fields["publication_id"]}
        if action in {"knowledge_open", "knowledge_preview"}:
            reader = (
                services.open_material if action == "knowledge_open" else services.preview_material
            )
            context["material"] = reader(**common, revision_id=fields["revision_id"])
            template = "material"
        elif action == "knowledge_history":
            context.update(services.history(**common))
            template = "history"
        elif action == "knowledge_browse":
            context.update(services.browse(**common, query=query))
            template = "browse"
        else:
            if action == "knowledge_propose":
                target_id = fields["target_id"]
                if fields["kind"] == "REFERENCE":
                    try:
                        target_id = int(target_id)
                    except ValueError as exc:
                        raise InvalidForm("knowledge_target_invalid") from exc
                services.propose(
                    **common,
                    kind=fields["kind"],
                    target_id=target_id,
                    reason=fields["reason"],
                    replaces_id=fields["replaces_id"] or None,
                )
            elif action in {"knowledge_approve", "knowledge_withdraw"}:
                services.act(
                    **common,
                    revision_id=fields["revision_id"],
                    action="APPROVE" if action == "knowledge_approve" else "WITHDRAW",
                    confirmed=fields["confirm"] == "yes",
                )
            context.update(services.desk(**common))
            template = "desk"
        return private(render(request, f"knowledge_links/{template}.html", context))
    except (InvalidForm, SuspiciousOperation):
        return denied("knowledge_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("knowledge_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("knowledge_store_unavailable", 503)
