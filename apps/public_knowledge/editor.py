"""Native CSRF-protected curation and explicit review/release commands."""

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
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service

from . import public, services

SAVE_FIELDS = {
    "pk_save_scholar": {"name", "bio"},
    "pk_save_topic": {"title", "introduction", "parent_id"},
    "pk_save_presentation": {"title", "question", "body", "description", "scholar_id", "language"},
    "pk_save_lesson": {"title", "summary", "lesson_choice"},
}
ACTIONS = frozenset({"pk_open", "pk_revision", "pk_act", *SAVE_FIELDS})
PINS = {"revision", "evidence_version"}


def _zero_integer(value):
    return 0 if value == "0" else _integer(value)


def _fields(request, action):
    required = {"action", "case_ref"}
    repeated = set()
    if action == "pk_revision":
        required.add("revision_id")
    elif action == "pk_act":
        required |= PINS | {
            "revision_id",
            "expected_actions",
            "command",
            "request_key",
            "note",
            "minutes",
            "related_id",
            "confirmed",
        }
    elif action in SAVE_FIELDS:
        required |= (
            PINS
            | {"publication_id", "series_id", "expected_version", "request_key"}
            | SAVE_FIELDS[action]
        )
        if action in {"pk_save_presentation", "pk_save_lesson"}:
            repeated.add("topic_ids")
        if action == "pk_save_lesson":
            repeated.add("scholar_ids")
        if action == "pk_save_presentation":
            repeated.add("relation_ids")
    if not repeated:
        return _form(request, required)
    allowed = required | repeated | {"csrfmiddlewaretoken"}
    if (
        request.content_type != "application/x-www-form-urlencoded"
        or request.FILES
        or not required | {"csrfmiddlewaretoken"} <= set(request.POST) <= allowed
        or any(len(values) != 1 for key, values in request.POST.lists() if key not in repeated)
        or any(len(request.POST.getlist(key)) > 8 for key in repeated)
    ):
        raise InvalidForm("public_knowledge_form_invalid")
    return request.POST


@mutation_service
def _page(request, common, *, selected_id=None, message="", code=200):
    # A read-only history pin belongs outside all desk/selected/render callbacks.
    # Writers keep their own expected-version checks instead of this pre-write pin.
    with synthetic_queue_atomic():
        with services.staff_boundary(**common) as (case, _):
            history = public._history_state([case.pk])
            result = services.desk(**common)
            selected = (
                services.read_revision(**common, revision_id=selected_id) if selected_id else None
            )
            choices = [row for row in result["records"] if row["stage"] == "APPROVED"]
            context = {
                "result": result,
                "selected": selected,
                "message": message,
                "scholars": [row for row in choices if row["kind"] == "SCHOLAR"],
                "topics": [row for row in choices if row["kind"] == "TOPIC"],
                "command_key": str(uuid.uuid4()),
                "lesson_choices": result.get("lesson_choices", []),
                "relation_choices": result.get("relation_choices", []),
            }
            for row in result["records"]:
                row["request_key"] = str(uuid.uuid4())
            get_token(request)
            response = private(
                render(request, "public_knowledge/editor.html", context, status=code)
            )
        # staff_boundary may itself resolve live authority/identity callbacks on
        # exit. Keep this pure comparison and the outer transaction after them.
        if public._history_state([case.pk]) != history:
            raise cases.CaseConflict("public_knowledge_read_history_changed")
        return response


@sensitive_post_parameters()
@csrf_protect
def workspace(request):
    try:
        services.enabled()
        action = request.POST.get("action")
        if request.method != "POST" or request.GET or action not in ACTIONS:
            raise InvalidForm("public_knowledge_form_invalid")
        fields = _fields(request, action)
        directory = _provider()
        actor = current_staff(request, directory, case_key=fields["case_ref"])
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        selected_case = next(
            (row for row in cases.list_cases(**common) if row["public_ref"] == fields["case_ref"]),
            None,
        )
        if selected_case is None:
            return denied("public_knowledge_case_unavailable", 404)
        common["case_id"] = selected_case["case_id"]
        if action == "pk_revision":
            return _page(request, common, selected_id=fields["revision_id"])
        if action == "pk_act":
            services.act(
                **common,
                revision_id=fields["revision_id"],
                expected_actions=_zero_integer(fields["expected_actions"]),
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
                action=fields["command"],
                request_key=fields["request_key"],
                note=fields["note"],
                minutes=_zero_integer(fields["minutes"]),
                related_id=fields["related_id"],
                confirmed=fields["confirmed"] == "yes",
            )
            return _page(
                request,
                common,
                message="حُفظ القرار على هذه النسخة. الاعتماد والإتاحة التجريبية إجراءان منفصلان.",
            )
        if action in SAVE_FIELDS:
            kind = action.removeprefix("pk_save_").upper()
            payload = {
                key: fields[key] for key in SAVE_FIELDS[action] - {"language", "lesson_choice"}
            }
            if kind in {"PRESENTATION", "LESSON"}:
                payload["topic_ids"] = fields.getlist("topic_ids")
            if kind == "PRESENTATION":
                payload["relation_ids"] = fields.getlist("relation_ids")
            if kind == "LESSON":
                parts = fields["lesson_choice"].split("|")
                if len(parts) != 3:
                    raise InvalidForm("public_lesson_choice_invalid")
                payload.update(
                    lesson_public_id=parts[0],
                    lesson_version=_integer(parts[1]),
                    lesson_sha256=parts[2],
                    scholar_ids=fields.getlist("scholar_ids"),
                )
            services.save(
                **common,
                publication_id=fields["publication_id"],
                kind=kind,
                language=fields.get("language", ""),
                series_id=fields["series_id"],
                expected_version=_zero_integer(fields["expected_version"]),
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
                payload=payload,
                request_key=fields["request_key"],
            )
            return _page(
                request, common, message="حُفظت نسخة مستقلة؛ لم تُعتمد ولم تظهر للقارئ بهذه الخطوة."
            )
        return _page(request, common)
    except cases.CaseConflict:
        return denied("public_knowledge_action_not_accepted", 409)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError):
        return denied("public_knowledge_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("public_knowledge_store_unavailable", 503)
