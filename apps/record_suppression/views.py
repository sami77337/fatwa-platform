"""Native preview and confirmation using the current actual administrative session."""

import uuid
from hmac import compare_digest

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web import access
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.operational_workspace import access as operational_access
from apps.operational_workspace import identity

from . import catalog, services

STAFF_PATH = "/casework/staff/record-lifecycle/"
OPERATIONAL_PATH = "/casework/operations/record-lifecycle/"


def _common(request):
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if request.path == OPERATIONAL_PATH:
        actor, until = operational_access.current(request, directory)
        provider = identity.RequestDirectory(directory, actor)
    elif request.path == STAFF_PATH:
        actor = access.current_staff(request, directory)
        until = actor.valid_until
        provider = access.RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
    else:
        raise InvalidForm("suppression_path_invalid")
    return {
        "provider": provider,
        "subject_id": actor.subject_id,
        "session_deadline": until,
        "synthetic_fixtures_only": True,
    }


def _fields(request):
    if request.GET or request.FILES or request.method not in {"GET", "POST"}:
        raise InvalidForm("suppression_form_invalid")
    if request.method == "GET":
        return {"action": "rs_open"}
    action = request.POST.get("action")
    fields = {"action"}
    if action == "rs_inspect":
        fields |= {"kind", "identifier"}
    elif action == "rs_preview":
        fields |= {
            "operation",
            "kind",
            "identifier",
            "source_digest",
            "head",
            "watermark",
            "reason",
            "request_key",
        }
    elif action == "rs_apply":
        fields |= {"plan", "proof", "confirmed"}
    elif action != "rs_open":
        raise InvalidForm("suppression_form_invalid")
    if (
        request.content_type != "application/x-www-form-urlencoded"
        or set(request.POST) != fields | {"csrfmiddlewaretoken"}
        or any(len(value) != 1 for _, value in request.POST.lists())
    ):
        raise InvalidForm("suppression_form_invalid")
    return {key: request.POST[key] for key in fields}


def _proof(request, base, plan):
    return browser_proof(
        request,
        "fatwa.suppression-preview.v1",
        catalog.digest([request.path, base["provider"].provider_id, base["subject_id"], plan]),
    )


@sensitive_post_parameters("reason", "plan")
@csrf_protect
def workspace(request):
    try:
        fields, base = _fields(request), _common(request)
        if fields["action"] == "rs_open":
            with services.desk(**base) as result:
                return private(
                    render(
                        request,
                        "record_suppression/desk.html",
                        {"result": result, "request_key": str(uuid.uuid4())},
                    )
                )
        if fields["action"] == "rs_inspect":
            with services.inspect(
                kind=fields["kind"], identifier=fields["identifier"], **base
            ) as result:
                return private(
                    render(
                        request,
                        "record_suppression/item.html",
                        {**result, "request_key": str(uuid.uuid4())},
                    )
                )
        if fields["action"] == "rs_preview":
            proposal = {
                name: value for name, value in fields.items() if name not in {"operation", "action"}
            }
            proposal["action"] = fields["operation"]
            with services.preview(proposal=proposal, **base) as plan:
                return private(
                    render(
                        request,
                        "record_suppression/preview.html",
                        {
                            "plan": plan,
                            "serialized": catalog.canonical(plan),
                            "proof": _proof(request, base, plan),
                        },
                    )
                )
        plan = services.decode(fields["plan"])
        if fields["confirmed"] != "yes" or not compare_digest(
            fields["proof"], _proof(request, base, plan)
        ):
            raise InvalidForm("suppression_preview_invalid")
        with services.apply(plan=plan, confirmed=True, **base) as result:
            return private(render(request, "record_suppression/saved.html", {"result": result}))
    except IdentityUnavailable:
        return denied("suppression_current_session_required", 403)
    except (catalog.SuppressionDenied, cases.CaseConflict):
        return denied("suppression_change_unavailable", 409)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError, KeyError):
        return denied("suppression_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("suppression_store_unavailable", 503)
