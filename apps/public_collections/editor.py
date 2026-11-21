"""Native bounded POST forms. Each response remains inside the full read boundary."""

import uuid

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.library_preview import services as preview
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service

from . import services

ACTIONS = frozenset({"pc_open", "pc_revision", "pc_save", "pc_reorder", "pc_act"})
PINS = {"revision", "evidence_version", "request_key"}


def zero_integer(value):
    return 0 if value == "0" else _integer(value)


def fields(request, action):
    required = {"action", "case_ref"}
    if action == "pc_revision":
        required.add("revision_id")
    elif action == "pc_act":
        required |= PINS | {
            "revision_id",
            "expected_actions",
            "command",
            "note",
            "minutes",
            "related_id",
            "confirmed",
        }
    elif action == "pc_reorder":
        required |= PINS | {"revision_id", "expected_version", "index", "direction"}
    elif action == "pc_save":
        required |= PINS | {
            "series_id",
            "expected_version",
            "kind",
            "title",
            "introduction",
            "parent_id",
        }
        if (
            request.content_type != "application/x-www-form-urlencoded"
            or request.FILES
            or not required | {"csrfmiddlewaretoken"}
            <= set(request.POST)
            <= required | {"csrfmiddlewaretoken", "members", "featured"}
            or any(len(values) != 1 for key, values in request.POST.lists() if key != "members")
            or len(request.POST.getlist("members")) > services.MAX_MEMBERS
            or request.POST.get("featured", "") not in {"", "yes"}
        ):
            raise InvalidForm("collection_form_invalid")
        return request.POST
    return _form(request, required)


@mutation_service
def page(request, common, *, selected_id=None, message=""):
    with services.scope(extra_case_ids=[common["case_id"]], freeze_history=True) as guard:
        result = services.desk_locked(
            guard,
            **{key: common[key] for key in ("case_id", "subject_id", "provider")},
            selected_id=selected_id,
        )
        selected = result["selected"]
        by_key = {row["selection"]: row for row in result["choices"]}
        ordered = []
        if selected and selected["available"]:
            for member in selected["members"]:
                choice = by_key.pop(member["selection"], None)
                if choice:
                    ordered.append({**choice, "checked": True})
        ordered.extend({**row, "checked": False} for row in by_key.values())
        result["choices"] = ordered
        for record in result["records"]:
            record["request_key"] = str(uuid.uuid4())
        if selected:
            selected["current"] = any(row["id"] == selected["id"] for row in result["records"])
        get_token(request)
        return private(
            render(
                request,
                "public_collections/editor.html",
                {
                    "result": result,
                    "selected": selected,
                    "message": message,
                    "command_key": str(uuid.uuid4()),
                },
            )
        )


@sensitive_post_parameters()
@csrf_protect
def workspace(request):
    try:
        services.enabled()
        action = request.POST.get("action")
        if request.method != "POST" or request.GET or action not in ACTIONS:
            raise InvalidForm("collection_form_invalid")
        values = fields(request, action)
        directory = _provider()
        actor = current_staff(request, directory, case_key=values["case_ref"])
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        selected_case = next(
            (row for row in cases.list_cases(**common) if row["public_ref"] == values["case_ref"]),
            None,
        )
        if selected_case is None:
            return denied("collection_case_unavailable", 404)
        common["case_id"] = selected_case["case_id"]
        with synthetic_queue_atomic():
            if action == "pc_open":
                return page(request, common)
            if action == "pc_revision":
                return page(request, common, selected_id=values["revision_id"])
            pins = dict(
                expected_revision=_integer(values["revision"]),
                expected_evidence_version=_integer(values["evidence_version"]),
                request_key=values["request_key"],
            )
            if action == "pc_save":
                result = services.save(
                    **common,
                    **pins,
                    kind=values["kind"],
                    title=values["title"],
                    introduction=values["introduction"],
                    members=values.getlist("members"),
                    featured=values.get("featured") == "yes",
                    parent_id=values["parent_id"],
                    series_id=values["series_id"],
                    expected_version=zero_integer(values["expected_version"]),
                )
                return page(
                    request,
                    common,
                    selected_id=result["id"],
                    message="حُفظت نسخة جديدة بترتيبها. تحتاج مراجعة واعتمادًا وإتاحة صريحة.",
                )
            if action == "pc_reorder":
                result = services.reorder(
                    **common,
                    **pins,
                    revision_id=values["revision_id"],
                    expected_version=_integer(values["expected_version"]),
                    index=zero_integer(values["index"]),
                    direction=values["direction"],
                )
                return page(
                    request,
                    common,
                    selected_id=result["id"],
                    message="حُفظ الترتيب في نسخة جديدة؛ بقيت النسخة السابقة في التاريخ.",
                )
            result = services.act(
                **common,
                **pins,
                revision_id=values["revision_id"],
                action=values["command"],
                expected_actions=zero_integer(values["expected_actions"]),
                note=values["note"],
                minutes=zero_integer(values["minutes"]),
                related_id=values["related_id"],
                confirmed=values["confirmed"] == "yes",
            )
            return page(
                request, common, selected_id=result["id"], message="حُفظ القرار على النسخة المحددة."
            )
    except (InvalidForm, ValueError, SuspiciousOperation):
        return denied("collection_form_or_state_invalid", 409)
    except (IdentityUnavailable, cases.CaseConflict, preview.PreviewUnavailable):
        return denied("collection_unavailable_or_changed", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("collection_storage_unavailable", 503)
