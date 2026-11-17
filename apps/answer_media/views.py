"""Native forms and authenticated byte responses for the closed media answer demo."""

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web import requester_workspace
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services

ACTIONS = frozenset({"answer_media", "answer_media_save", "answer_media_release"})


def _staff(request):
    directory = _provider()
    identity = current_staff(request, directory)
    return identity, RequestDirectory(
        directory, identity, authenticated_provider_id=directory.provider_id
    )


def _multipart(request):
    required = {
        "action",
        "case_ref",
        "revision",
        "evidence_version",
        "text",
        "retain",
        "synthetic_only",
        "csrfmiddlewaretoken",
    }
    if (
        request.content_type != "multipart/form-data"
        or set(request.POST) != required
        or any(len(request.POST.getlist(k)) != 1 for k in request.POST)
        or set(request.FILES) not in (set(), {"answer_file"})
        or len(request.FILES.getlist("answer_file")) > 1
        or request.POST["synthetic_only"] != "yes"
        or request.POST["retain"] not in {"yes", "no"}
    ):
        raise InvalidForm("answer_media_form_invalid")
    return request.POST


@sensitive_post_parameters()
@csrf_protect
def staff(request):
    try:
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("answer_media_form_invalid")
        identity, provider = _staff(request)
        action = request.POST.get("action")
        required = {"action", "case_ref"}
        if action == "answer_media_release":
            required |= {"revision", "evidence_version", "manifest_sha256", "confirm"}
        fields = _multipart(request) if action == "answer_media_save" else _form(request, required)
        common = {
            "subject_id": identity.subject_id,
            "provider": provider,
            "synthetic_fixtures_only": True,
        }
        scoped = cases.list_cases(**common)
        selected = next((row for row in scoped if row["public_ref"] == fields["case_ref"]), None)
        if selected is None:
            return denied("answer_media_unavailable", 404)
        common["case_id"] = selected["case_id"]
        if action == "answer_media_save":
            current = services.staff_snapshot(**common)
            retained = (
                [
                    p["id"]
                    for p in (current["latest_package"] or {}).get("parts", [])
                    if p["kind"] != "TEXT"
                ]
                if fields["retain"] == "yes"
                else []
            )
            uploaded = request.FILES.get("answer_file")
            files = []
            if uploaded:
                if uploaded.size > 192000:
                    return denied("answer_media_too_large", 413)
                files.append(
                    {
                        "raw": uploaded.read(192001),
                        "filename": uploaded.name,
                        "media_type": uploaded.content_type,
                    }
                )
            services.save_multipart_answer(
                **common,
                text=fields["text"],
                files=files,
                retained_part_ids=retained,
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
            )
        elif action == "answer_media_release":
            services.release_private(
                **common,
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
                manifest_sha256=fields["manifest_sha256"],
                confirmed=fields["confirm"] == "yes",
            )
        get_token(request)
        return private(
            render(
                request,
                "answer_media/staff.html",
                {
                    "selected": services.staff_snapshot(**common),
                    "saved": action != "answer_media",
                    "release_enabled": getattr(
                        settings, "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED", False
                    )
                    is True,
                },
            )
        )
    except (InvalidForm, SuspiciousOperation):
        return denied("answer_media_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("answer_media_unavailable_or_stale", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("answer_media_store_unavailable", 503)


@sensitive_post_parameters()
@csrf_protect
def requester(request):
    try:
        _form(request, {"action"})
        if request.POST["action"] != "answer_media":
            raise InvalidForm("answer_media_form_invalid")
        result = services.requester_snapshot(
            token=requester_workspace._capability(request), synthetic_fixtures_only=True
        )
        get_token(request)
        return private(render(request, "answer_media/requester.html", result))
    except (InvalidForm, SuspiciousOperation):
        return denied("answer_media_form_invalid", 400)
    except cases.CaseConflict:
        return denied("private_answer_media_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("answer_media_store_unavailable", 503)


def _file(row):
    response = private(
        HttpResponse(
            row["raw"],
            content_type=row["media_type"],
            headers={
                "Content-Disposition": f'inline; filename="{row["filename"]}"',
                "Content-Length": str(row["size"]),
                "Accept-Ranges": "none",
            },
        )
    )
    # Embedded content cannot execute scripts, submit forms or access another origin.
    response["Content-Security-Policy"] = "default-src 'none'; sandbox; frame-ancestors 'self'"
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


def staff_file(request, part_id):
    try:
        if request.method not in {"GET", "HEAD"}:
            return denied("answer_media_method_invalid", 405)
        actor, provider = _staff(request)
        response = _file(
            services.staff_read(
                part_id=str(part_id),
                subject_id=actor.subject_id,
                provider=provider,
                synthetic_fixtures_only=True,
            )
        )
        if request.method == "HEAD":
            response.content = b""
        return response
    except (IdentityUnavailable, cases.CaseConflict):
        return denied("answer_media_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("answer_media_store_unavailable", 503)


def requester_file(request, part_id):
    try:
        if request.method not in {"GET", "HEAD"}:
            return denied("answer_media_method_invalid", 405)
        response = _file(
            services.requester_read(
                token=requester_workspace._capability(request),
                part_id=str(part_id),
                synthetic_fixtures_only=True,
            )
        )
        if request.method == "HEAD":
            response.content = b""
        return response
    except cases.CaseConflict:
        return denied("answer_media_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("answer_media_store_unavailable", 503)


def dispatch_staff(request):
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return staff(request)
    from apps.requester_team_journey.views import staff as campaign_staff

    return campaign_staff(request)


def dispatch_requester(request):
    if request.method == "POST" and request.POST.get("action") == "answer_media":
        return requester(request)
    from apps.requester_access_review.views import requester as campaign_requester

    return campaign_requester(request)
