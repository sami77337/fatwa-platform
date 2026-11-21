"""Authenticated native curation and complete guarded anonymous source readers."""

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
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.library_preview import services as preview
from apps.library_preview.guard import safe_read
from apps.mufti_review.identity import IdentityUnavailable
from apps.public_answer_media.views import _file_response as original_response

from . import services

ACTIONS = {"pt_open", "pt_save", "pt_decide"}


def _zero(value):
    return 0 if value == "0" else _integer(value)


def _fields(request):
    if request.method != "POST" or request.GET or request.FILES:
        raise InvalidForm("teaching_form_invalid")
    action = request.POST.get("action", "")
    required = {"action", "case_ref"}
    if action not in ACTIONS:
        raise InvalidForm("teaching_form_invalid")
    if action != "pt_open":
        required |= {"revision", "evidence_version", "request_key", "note", "confirmed"}
    if action == "pt_save":
        kind = request.POST.get("kind", "")
        required |= {"kind", "title", "summary", "item_id", "expected_version"}
        additions = {
            "SCHOLAR_MATERIAL": {"profile", "material", "attribution"},
            "LESSON": {"lesson"},
            "SERIES": {"series", "topic", "teachers"},
        }
        if kind not in additions:
            raise InvalidForm("teaching_form_invalid")
        required |= additions[kind]
    elif action == "pt_decide":
        required |= {"version_id", "command", "expected_actions", "minutes"}
    allowed = required | {"csrfmiddlewaretoken"}
    if action == "pt_save" and request.POST.get("kind") == "SERIES":
        allowed.add("members")
    if not required <= set(request.POST) or set(request.POST) - allowed:
        raise InvalidForm("teaching_exact_fields_required")
    for name, values in request.POST.lists():
        if (name == "members" and not 1 <= len(values) <= 16) or (
            name != "members" and len(values) != 1
        ):
            raise InvalidForm("teaching_duplicate_fields")
    fields = {name: request.POST[name] for name in required}
    fields["members"] = request.POST.getlist("members")
    return fields


def _common(request, reference):
    directory = _provider()
    actor = current_staff(request, directory, case_key=reference)
    case = Case.objects.filter(public_ref=reference).first()
    if case is None:
        raise cases.CaseConflict("teaching_case_unavailable")
    return dict(
        case_id=str(case.pk),
        subject_id=actor.subject_id,
        provider=RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        ),
        synthetic_fixtures_only=True,
    )


def _page(request, base, message=""):
    with services.desk_projection(**base) as result:
        return private(
            render(
                request,
                "public_teaching/desk.html",
                {
                    "result": result,
                    "selected": {
                        "public_ref": result["case_ref"],
                        "revision": result["revision"],
                        "evidence_version": result["evidence_version"],
                    },
                    "request_key": str(uuid.uuid4()),
                    "message": message,
                },
            )
        )


@csrf_protect
def workspace(request):
    try:
        services.enabled()
        fields = _fields(request)
        base = _common(request, fields["case_ref"])
        with synthetic_queue_atomic(), services.staff_scope(**base):
            action = fields["action"]
            if action != "pt_open":
                common = dict(
                    base,
                    expected_revision=_integer(fields["revision"]),
                    expected_evidence_version=_integer(fields["evidence_version"]),
                    request_key=fields["request_key"],
                    note=fields["note"],
                    confirmed=fields["confirmed"] == "yes",
                )
                if action == "pt_save":
                    services.save(
                        **common,
                        kind=fields["kind"],
                        title=fields["title"],
                        summary=fields["summary"],
                        item_id=fields["item_id"] or None,
                        expected_version=_zero(fields["expected_version"]),
                        profile=fields.get("profile", ""),
                        material=fields.get("material", ""),
                        lesson=fields.get("lesson", ""),
                        series=fields.get("series", ""),
                        attribution=fields.get("attribution", ""),
                        topic=fields.get("topic", ""),
                        teacher_labels=[
                            line.strip()
                            for line in fields.get("teachers", "").splitlines()
                            if line.strip()
                        ],
                        members=fields["members"],
                    )
                else:
                    services.decide(
                        **common,
                        version_id=fields["version_id"],
                        command=fields["command"],
                        expected_actions=_zero(fields["expected_actions"]),
                        minutes=_zero(fields["minutes"]),
                    )
            return _page(
                request,
                base,
                "حُفظ الإجراء وسجله. الإتاحة تخص النسخة والمصادر المحددة وتحتاج صلاحياتها الحالية."
                if action != "pt_open"
                else "",
            )
    except IdentityUnavailable:
        return denied("teaching_current_staff_required", 403)
    except cases.CaseConflict:
        return denied("teaching_current_source_or_authority_changed", 409)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError):
        return denied("teaching_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("teaching_store_unavailable", 503)


def _query(request):
    if request.GET:
        raise preview.InvalidFilter()


def _public_page(request, template, context, *, media=False):
    response = render(request, template, context)
    if media:
        response._allow_library_media = True
    return response


@safe_read
def catalog(request):
    _query(request)
    with services.public_projection(search=True) as current:
        return _public_page(request, "public_teaching/catalog.html", current.catalog())


@safe_read
def scholar(request, public_id):
    _query(request)
    with services.public_projection() as current:
        return _public_page(
            request, "public_teaching/scholar.html", {"scholar": current.scholar(public_id)}
        )


@safe_read
def lesson(request, public_id, series_id=None):
    _query(request)
    with services.public_projection() as current:
        return _public_page(
            request,
            "public_teaching/lesson.html",
            {"lesson": current.lesson(public_id, series_id=series_id)},
            media=True,
        )


@safe_read
def series(request, public_id):
    _query(request)
    with services.public_projection() as current:
        _, row = current.read(public_id, "SERIES")
        return _public_page(request, "public_teaching/series.html", {"series": row})


@safe_read
def audio(request, public_id, number):
    _query(request)
    with services.public_projection() as current:
        result = current.audio(public_id, number)
        return original_response(request, result)
