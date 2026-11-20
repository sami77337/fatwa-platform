"""Native staff forms for versioned lessons, explicit links and precise filters."""

import uuid
from functools import wraps

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError, transaction
from django.http import HttpResponse
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

SEARCH_FIELDS = {
    "query",
    "series_id",
    "lesson_id",
    "category_id",
    "relation_kind",
    "related_case_ref",
}
BASE = {"action", "case_ref"}
PINS = {"revision", "evidence_version", "command_id"}
SHAPES = {
    "scholarly_open": BASE,
    "scholarly_search_open": BASE,
    "scholarly_search": BASE | SEARCH_FIELDS,
    "lesson_category_create": BASE | PINS | {"label"},
    "lesson_series_save": BASE
    | PINS
    | {"series_id", "series_version", "title", "teachers", "teacher_is_me"},
    "lesson_save": BASE
    | PINS
    | {
        "series_id",
        "series_version",
        "lesson_id",
        "lesson_version",
        "title",
        "category_id",
        "source_part_id",
        "provenance",
    },
    "lesson_move": BASE | PINS | {"series_id", "series_version", "lesson_id", "direction"},
    "lesson_view": BASE | {"lesson_version_id"},
    "lesson_media": BASE | {"lesson_version_id"},
    "relation_propose": BASE | PINS | {"target", "kind", "reason"},
    "lesson_link_propose": BASE | PINS | {"lesson_target", "start_ms", "end_ms", "reason"},
    "scholarly_review": BASE
    | PINS
    | {
        "link_id",
        "link_kind",
        "transition",
        "sequence",
        "target_revision",
        "target_evidence_version",
        "note",
    },
}
ACTIONS = frozenset(SHAPES)


def _zero(raw):
    return 0 if raw == "0" else _integer(raw)


def _optional(raw):
    return None if raw == "" else _zero(raw)


def _selection(raw, count):
    fields = raw.split(":")
    if len(fields) != count:
        raise InvalidForm("scholarly_selection_invalid")
    return fields


def _render(request, template, result, **context):
    guard = result.pop("_guard")
    response = render(
        request,
        template,
        {
            "scholarly": result,
            "command_id": str(uuid.uuid4()),
            "relation_kinds": services.KIND_LABELS.items(),
            **context,
        },
    )
    # Context processors and template rendering are another composition boundary.
    guard.check()
    return private(response)


def _desk(request, common, *, notice=""):
    result = services.desk(**common)
    for series in result["own_series"]:
        series["teacher_text"] = "\n".join(row["name"] for row in series["teachers"])
        series["teacher_is_me"] = bool(
            series["teachers"]
            and series["teachers"][0].get("subject_id") == common["subject_id"]
            and series["teachers"][0].get("provider_id") == common["provider"].provider_id
        )
    return _render(request, "scholarly_links/desk.html", result, notice=notice)


def _projection_transaction(function):
    """Keep canonical locks through template/context and the final watermark."""

    @wraps(function)
    def wrapped(request):
        try:
            services._enabled()
            cases._guard(True)
            with synthetic_queue_atomic():
                # Match relation SQL/public projections before dispatch or
                # directory callbacks can retain any canonical case locks.
                services._graph_lock()
                response = function(request)
                if response.status_code >= 400:
                    transaction.set_rollback(True)
                return response
        except cases.CaseConflict:
            return denied("scholarly_unavailable_or_changed", 409)
        except (DatabaseError, SyntheticWriteDenied):
            return denied("scholarly_store_unavailable", 503)

    return wrapped


@sensitive_post_parameters("reason", "note", "provenance", "teachers")
@csrf_protect
@_projection_transaction
def workspace(request):
    try:
        services._enabled()
        action = request.POST.get("action")
        if request.method != "POST" or action not in ACTIONS or request.FILES:
            raise InvalidForm("scholarly_form_invalid")
        fields = _form(request, SHAPES[action])
        directory = _provider()
        identity = current_staff(request, directory, case_key=fields["case_ref"])
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        common = dict(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        # The response catalog reads the whole current scope after a command.
        # Lock that complete set in UUID order before a command can retain only
        # its subset. Services still validate each case and current identity;
        # this early lock set grants no read or mutation authority.
        scoped_cases = list(
            Case.objects.filter(public_ref__in=identity.case_keys)
            .order_by("id")
            .select_for_update()
        )
        selected = next((row for row in scoped_cases if row.public_ref == fields["case_ref"]), None)
        if selected is None:
            return denied("scholarly_case_unavailable", 404)
        if action in {"scholarly_search", "scholarly_search_open"}:
            from apps.research_workspace.scholarly_adapter import search

            filters = (
                {key: fields[key] for key in SEARCH_FIELDS} if action == "scholarly_search" else {}
            )
            result = search(**common, **filters)
            return _render(
                request, "scholarly_links/search.html", result, case_ref=fields["case_ref"]
            )
        common["case_id"] = selected.pk
        if action == "lesson_view":
            result = services.read_lesson(**common, lesson_version_id=fields["lesson_version_id"])
            return _render(
                request, "scholarly_links/lesson.html", result, case_ref=fields["case_ref"]
            )
        if action == "lesson_media":
            result = services.open_lesson_media(
                **common, lesson_version_id=fields["lesson_version_id"]
            )
            response = HttpResponse(
                result["raw"],
                content_type=result["media_type"],
                headers={
                    "Content-Disposition": f'inline; filename="{result["filename"]}"',
                    "Content-Length": str(len(result["raw"])),
                    "Accept-Ranges": "none",
                },
            )
            result["_guard"].check()
            return private(response)
        if action == "scholarly_open":
            return _desk(request, common)
        mutation = dict(
            **common,
            command_id=fields["command_id"],
            expected_revision=_integer(fields["revision"]),
            expected_evidence_version=_integer(fields["evidence_version"]),
        )
        if action == "lesson_category_create":
            services.create_category(**mutation, label=fields["label"])
        elif action == "lesson_series_save":
            if fields["teacher_is_me"] not in {"yes", "no"}:
                raise InvalidForm("scholarly_teacher_invalid")
            teachers = [
                {"name": name.strip()} for name in fields["teachers"].splitlines() if name.strip()
            ]
            if teachers and fields["teacher_is_me"] == "yes":
                teachers[0].update(provider_id=provider.provider_id, subject_id=identity.subject_id)
            services.save_series(
                **mutation,
                series_id=fields["series_id"] or None,
                expected_series_version=_zero(fields["series_version"]),
                title=fields["title"],
                teachers=teachers,
            )
        elif action == "lesson_save":
            services.save_lesson(
                **mutation,
                series_id=fields["series_id"],
                expected_series_version=_integer(fields["series_version"]),
                lesson_id=fields["lesson_id"] or None,
                expected_lesson_version=_zero(fields["lesson_version"]),
                title=fields["title"],
                category_id=fields["category_id"],
                source_part_id=fields["source_part_id"] or None,
                provenance=fields["provenance"],
            )
        elif action == "lesson_move":
            services.move_lesson(
                **mutation,
                series_id=fields["series_id"],
                expected_series_version=_integer(fields["series_version"]),
                lesson_id=fields["lesson_id"],
                direction=fields["direction"],
            )
        elif action == "relation_propose":
            target, answer, revision, evidence = _selection(fields["target"], 4)
            services.propose_relation(
                **mutation,
                target_case_id=target,
                target_answer_id=answer,
                expected_target_revision=_integer(revision),
                expected_target_evidence_version=_integer(evidence),
                kind=fields["kind"],
                reason=fields["reason"],
            )
        elif action == "lesson_link_propose":
            lesson, revision, evidence = _selection(fields["lesson_target"], 3)
            services.propose_lesson_link(
                **mutation,
                lesson_version_id=lesson,
                expected_target_revision=_integer(revision),
                expected_target_evidence_version=_integer(evidence),
                start_ms=_optional(fields["start_ms"]),
                end_ms=_optional(fields["end_ms"]),
                reason=fields["reason"],
            )
        elif action == "scholarly_review":
            services.review_link(
                **mutation,
                link_id=fields["link_id"],
                link_kind=fields["link_kind"],
                action=fields["transition"],
                expected_sequence=_zero(fields["sequence"]),
                expected_target_revision=_integer(fields["target_revision"]),
                expected_target_evidence_version=_integer(fields["target_evidence_version"]),
                note=fields["note"],
            )
        return _desk(
            request,
            common,
            notice="حُفظ الإجراء وسجله. بقيت الوقائع والأجوبة وقرارات اعتمادها كما هي.",
        )
    except (InvalidForm, SuspiciousOperation, TypeError):
        request._mufti_workspace_error = True
        return denied("scholarly_form_invalid", 400)
    except IdentityUnavailable:
        request._mufti_workspace_error = True
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        request._mufti_workspace_error = True
        return denied("scholarly_unavailable_or_changed", 409)
    except (DatabaseError, SyntheticWriteDenied):
        request._mufti_workspace_error = True
        return denied("scholarly_store_unavailable", 503)


def dispatch(request):
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return workspace(request)
    from apps.requester_team_journey.views import staff

    return staff(request)
