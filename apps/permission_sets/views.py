"""Native administrative preview and confirmation through the actual staff session."""

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

from . import boundary, catalog, services

STAFF_PATH = "/casework/staff/permissions/"
OPERATIONAL_PATH = "/casework/operations/permissions/"
ACTIONS = {"ps_open", "ps_new", "ps_inspect", "ps_preview", "ps_apply"}


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
        raise InvalidForm("permission_path_invalid")
    return {
        "provider": provider,
        "subject_id": actor.subject_id,
        "session_deadline": until,
        "synthetic_fixtures_only": True,
    }


def _fields(request):
    if request.GET or request.FILES or request.method not in {"GET", "POST"}:
        raise InvalidForm("permission_form_invalid")
    if request.method == "GET":
        return {"action": "ps_open"}
    action = request.POST.get("action")
    required, multiple = {"action"}, set()
    if action == "ps_inspect":
        required |= {"kind", "key"}
    elif action == "ps_apply":
        required |= {"plan", "proof", "confirmed"}
    elif action == "ps_preview":
        required |= {"kind", "key", "change", "expected_digest", "note", "minutes", "request_key"}
        change, kind = request.POST.get("change"), request.POST.get("kind")
        if change in {"CREATE", "REPLACE"}:
            multiple |= {"allow", "deny"}
            if kind == "SET":
                required.add("title")
            elif kind == "USER":
                multiple.add("sets")
            else:
                raise InvalidForm("permission_form_invalid")
        elif change == "REVERT":
            required.add("reverted_from")
        elif change != "DISABLE":
            raise InvalidForm("permission_form_invalid")
    if action not in ACTIONS or request.content_type != "application/x-www-form-urlencoded":
        raise InvalidForm("permission_form_invalid")
    if not required | {"csrfmiddlewaretoken"} <= set(request.POST) or set(
        request.POST
    ) - required - multiple - {"csrfmiddlewaretoken"}:
        raise InvalidForm("permission_form_invalid")
    for name, values in request.POST.lists():
        if name in multiple:
            if len(values) > (catalog.MAX_SETS if name == "sets" else catalog.MAX_RULES):
                raise InvalidForm("permission_form_bound")
        elif len(values) != 1:
            raise InvalidForm("permission_duplicate_fields")
    return {name: request.POST[name] for name in required} | {
        name: request.POST.getlist(name) for name in multiple
    }


def _proposal(fields, common):
    definition = None
    if fields["change"] in {"CREATE", "REPLACE"}:
        with boundary.scope(**common) as guard:
            choices = guard.choices()
            rules = []
            for name, effect in (("allow", "ALLOW"), ("deny", "DENY")):
                for key in fields[name]:
                    if key not in choices:
                        raise InvalidForm("permission_selection_unavailable")
                    rules.append({"scope": choices[key], "effect": effect})
            definition = (
                {"title": fields["title"], "rules": rules}
                if fields["kind"] == "SET"
                else {
                    "sets": fields["sets"],
                    "overrides": rules,
                }
            )
    return {
        "kind": fields["kind"],
        "key": fields["key"],
        "change": fields["change"],
        "definition": definition,
        "expected_digest": fields["expected_digest"],
        "note": fields["note"],
        "minutes": int(fields["minutes"]),
        "request_key": fields["request_key"],
        "reverted_from": fields.get("reverted_from"),
    }


def _proof(request, common, plan):
    actor = common["provider"].resolve(common["subject_id"])
    return browser_proof(
        request,
        "fatwa.permission-preview.v1",
        catalog.digest(
            [
                request.path,
                common["provider"].provider_id,
                actor.subject_id,
                actor.role,
                actor.auth_epoch,
                plan,
            ]
        ),
    )


def _item(request, common, kind, key):
    with services.inspect(kind=kind, key=key, **common) as item:
        current = item["current"]
        definition = current["definition"] if current else {}
        rules = definition.get("rules", definition.get("overrides", []))
        effects = {catalog.digest(rule["scope"]): rule["effect"] for rule in rules}
        for choice in item["choices"]:
            choice["effect"] = effects.get(choice["key"], "")
        for selected in item["sets"]:
            selected["selected"] = selected["key"] in definition.get("sets", [])
        return private(
            render(
                request,
                "permission_sets/item.html",
                {
                    "item": item,
                    "request_key": str(uuid.uuid4()),
                    "change": "REPLACE" if current else "CREATE",
                },
            )
        )


@sensitive_post_parameters("note", "plan")
@csrf_protect
def workspace(request):
    try:
        fields = _fields(request)
        common = _common(request)
        action = fields["action"]
        if action == "ps_open":
            with services.desk(**common) as result:
                return private(render(request, "permission_sets/desk.html", {"result": result}))
        if action == "ps_new":
            return _item(request, common, "SET", str(uuid.uuid4()))
        if action == "ps_inspect":
            return _item(request, common, fields["kind"], fields["key"])
        if action == "ps_preview":
            with services.preview(proposal=_proposal(fields, common), **common) as plan:
                return private(
                    render(
                        request,
                        "permission_sets/preview.html",
                        {
                            "plan": plan,
                            "serialized": catalog.canonical(plan),
                            "proof": _proof(request, common, plan),
                        },
                    )
                )
        plan = services.decode(fields["plan"])
        if fields["confirmed"] != "yes" or not compare_digest(
            fields["proof"], _proof(request, common, plan)
        ):
            raise InvalidForm("permission_preview_proof_invalid")
        with services.apply(plan=plan, confirmed=True, **common) as result:
            return private(render(request, "permission_sets/saved.html", {"result": result}))
    except IdentityUnavailable:
        return denied("permission_current_session_required", 403)
    except (catalog.PermissionDenied, cases.CaseConflict):
        return denied("permission_change_unavailable", 409)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError, KeyError):
        return denied("permission_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("permission_store_unavailable", 503)
