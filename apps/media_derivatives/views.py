"""Native finite job controls, original links and independently authorized output."""

import uuid

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.private_media import links

from . import policy, services
from .models import DerivativeJob
from .sources import Source

BASE = "/casework/staff/media-jobs/"
FIELDS = {
    "media_jobs_open": set(),
    "media_jobs_prepare": {"source", "task", "request_key", "revision", "evidence_version"},
    "media_jobs_status": {"job_id"},
    "media_jobs_retry": {"job_id", "request_key", "sequence"},
    "media_jobs_cancel": {"job_id", "request_key", "sequence"},
    "media_jobs_download": {"job_id"},
}


def _common(request, ref=None):
    directory = _provider()
    actor = current_staff(request, directory, **({"case_key": ref} if ref else {}))
    provider = RequestDirectory(directory, actor, authenticated_provider_id=directory.provider_id)
    common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
    if ref is not None:
        row = Case.objects.filter(public_ref=ref).first()
        if row is None:
            raise cases.CaseConflict("derivative_case_unavailable")
        common["case_id"] = row.pk
    return common


def _source_url(pin):
    return {
        "ATTACHMENT": "/casework/staff/attachments/{id}/",
        "ANSWER_PART": "/casework/staff/answer-media/{id}/",
        "LIBRARY_VERSION": "/casework/staff/library/{id}/file/",
    }[pin["kind"]].format(id=pin["id"])


def _page(request, common, *, message=""):
    with policy.response_projection():
        context = services.inventory(**common)
        for row in context["jobs"]:
            row["request_key"] = str(uuid.uuid4())
            row["original_url"] = links.issue(request, _source_url(row["source"]))
            if row["state"] == "READY":
                row["output_url"] = links.issue(request, BASE + row["id"] + "/output/")
                row["can_download"] = services.can_download(**common, job_id=row["id"])
        for row in context["choices"]:
            row["request_key"] = str(uuid.uuid4())
        context["message"] = message
        context["base"] = BASE
        get_token(request)
        return private(render(request, "media_derivatives/desk.html", context))


@csrf_protect
def workspace(request):
    try:
        policy.configuration()
        if request.GET:
            raise InvalidForm("derivative_query")
        if request.method in {"GET", "HEAD"}:
            common = _common(request)
            rows = cases.list_cases(**common)
            get_token(request)
            return private(
                render(request, "media_derivatives/entry.html", {"cases": rows, "base": BASE}),
                head=request.method == "HEAD",
            )
        action = request.POST.get("action", "")
        if (
            request.method != "POST"
            or action not in FIELDS
            or request.content_type != "application/x-www-form-urlencoded"
            or set(request.POST) != FIELDS[action] | {"action", "case_ref", "csrfmiddlewaretoken"}
            or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
        ):
            raise InvalidForm("derivative_form")
        values = request.POST
        common = _common(request, values["case_ref"])
        if action == "media_jobs_prepare":
            pieces = values["source"].split(":")
            if len(pieces) != 2:
                raise InvalidForm("derivative_source")
            services.prepare(
                **common,
                source=Source(*pieces),
                task=values["task"],
                request_key=values["request_key"],
                expected_revision=_integer(values["revision"]),
                expected_evidence_version=_integer(values["evidence_version"]),
            )
            return _page(
                request, common, message="حُفظ طلب المعالجة. ينفذه العامل المستقل؛ الأصل محفوظ."
            )
        if action in {"media_jobs_retry", "media_jobs_cancel"}:
            services.command(
                **common,
                job_id=values["job_id"],
                action="RETRY" if action == "media_jobs_retry" else "CANCEL",
                request_key=values["request_key"],
                expected_sequence=_integer(values["sequence"]),
            )
        elif action == "media_jobs_status":
            services.status(**common, job_id=values["job_id"])
        elif action == "media_jobs_download":
            result = services.download(**common, job_id=values["job_id"])
            response = private(HttpResponse(result["raw"], content_type=result["media_type"]))
            response["Content-Disposition"] = (
                'attachment; filename="'
                + ("playback.wav" if result["media_type"] == "audio/wav" else "thumbnail.png")
                + '"'
            )
            response["Referrer-Policy"] = "no-referrer"
            return response
        return _page(request, common)
    except (IdentityUnavailable, cases.CaseConflict):
        return denied("media_derivative_unavailable", 404)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError):
        return denied("media_derivative_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("media_derivative_store_unavailable", 503)


@links.protect
def output(request, job_id):
    try:
        policy.configuration()
        if request.method not in {"GET", "HEAD"} or request.GET:
            return denied("media_derivative_unavailable", 404)
        if links.enabled() and links.route(request.path) is None:
            # Missing coordinator wiring is closed, even if the app flag is on.
            return denied("media_derivative_unavailable", 404)
        row = DerivativeJob.objects.select_related("case").filter(pk=job_id).first()
        if row is None:
            return denied("media_derivative_unavailable", 404)
        common = _common(request, row.case.public_ref)
        result = services.read_output(**common, job_id=job_id)
        response = private(
            HttpResponse(result["raw"], content_type=result["media_type"]),
            head=request.method == "HEAD",
        )
        response["Content-Disposition"] = (
            'inline; filename="'
            + ("playback.wav" if result["media_type"] == "audio/wav" else "thumbnail.png")
            + '"'
        )
        response["Referrer-Policy"] = "no-referrer"
        return response
    except (cases.CaseConflict, IdentityUnavailable, ValueError, TypeError):
        response = denied("media_derivative_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        response = denied("media_derivative_store_unavailable", 503)
    response["Referrer-Policy"] = "no-referrer"
    return response
