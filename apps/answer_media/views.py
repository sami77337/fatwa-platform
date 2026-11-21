"""Native forms and authenticated byte responses for the closed media answer demo."""

from contextlib import contextmanager
from hashlib import sha256

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.case_attachments.storage_bindings import binding_locks
from apps.casework import services as cases
from apps.casework_web import requester_workspace
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.private_media.links import protect
from apps.private_media.storage import configured_storage

from . import related_views, services
from .editor_boundary import EditorBoundary, head

ACTIONS = (
    frozenset({"answer_media", "answer_media_save", "answer_media_release", "answer_media_reorder"})
    | related_views.ACTIONS
)


def _reorder(request):
    required = {
        "action",
        "case_ref",
        "revision",
        "evidence_version",
        "parts",
        "csrfmiddlewaretoken",
    }
    if (
        request.content_type != "application/x-www-form-urlencoded"
        or set(request.POST) != required
        or any(len(request.POST.getlist(key)) != 1 for key in required - {"parts"})
        or not 1 <= len(request.POST.getlist("parts")) <= 7
        or request.FILES
    ):
        raise InvalidForm("answer_media_reorder_invalid")
    return request.POST


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
    posted = set(request.POST)
    link_fields = {"youtube_url", "youtube_label"}
    if posted & link_fields:
        if (
            getattr(settings, "FATWA_ANSWER_LINKS_ENABLED", False) is not True
            or not link_fields <= posted
        ):
            raise InvalidForm("answer_link_form_invalid")
        required |= link_fields
    # Native browsers serialize an unselected optional file control as one
    # empty field. It is absence of a file, never a filename/path or an upload.
    if "answer_file" in posted:
        if request.POST.getlist("answer_file") != [""] or request.FILES:
            raise InvalidForm("answer_media_form_invalid")
        posted.remove("answer_file")
    if (
        request.content_type != "multipart/form-data"
        or posted != required
        or any(len(request.POST.getlist(k)) != 1 for k in request.POST)
        or set(request.FILES) not in (set(), {"answer_file"})
        or len(request.FILES.getlist("answer_file")) > 1
        or request.POST["synthetic_only"] != "yes"
        or request.POST["retain"] not in {"yes", "no"}
    ):
        raise InvalidForm("answer_media_form_invalid")
    return request.POST


def _enhanced():
    return any(
        getattr(settings, name, False) is True
        for name in ("FATWA_ANSWER_LINKS_ENABLED", "FATWA_ANSWER_RELATED_ENABLED")
    )


@contextmanager
def _editor_transaction(request, common):
    if not _enhanced():
        yield
        return
    storage = configured_storage()
    digests = []
    for uploaded in request.FILES.values():
        if uploaded.size > 192000:
            raise InvalidForm("answer_media_too_large")
        digests.append(sha256(uploaded.read(192001)).hexdigest())
        uploaded.seek(0)
    with binding_locks(storage, digests), synthetic_queue_atomic():
        editor = EditorBoundary(common["provider"])
        yield
        editor.check()


def _render_staff(request, common, action):
    expected = head(common["case_id"])
    selected = services.staff_snapshot(**common)
    related = related_views.seed(request, common, selected)
    get_token(request)
    response = private(
        render(
            request,
            "answer_media/staff.html",
            {
                "selected": selected,
                "related": related,
                "saved": action != "answer_media",
                "links_enabled": getattr(settings, "FATWA_ANSWER_LINKS_ENABLED", False) is True,
                "release_enabled": getattr(settings, "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED", False)
                is True,
            },
        )
    )
    if _enhanced():
        if services.staff_snapshot(**common) != selected or head(common["case_id"]) != expected:
            raise cases.CaseConflict("answer_editor_source_changed")
    return response


@sensitive_post_parameters()
@csrf_protect
def staff(request):
    if request.method == "POST" and request.POST.get("action") in related_views.ACTIONS:
        return related_views.workspace(request)
    try:
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("answer_media_form_invalid")
        identity, provider = _staff(request)
        action = request.POST.get("action")
        required = {"action", "case_ref"}
        if action == "answer_media_release":
            required |= {"revision", "evidence_version", "manifest_sha256", "confirm"}
        fields = (
            _multipart(request)
            if action == "answer_media_save"
            else _reorder(request)
            if action == "answer_media_reorder"
            else _form(request, required)
        )
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
        with _editor_transaction(request, common):
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
                    links=(
                        [
                            {
                                "url": fields.get("youtube_url", ""),
                                "label": fields.get("youtube_label", ""),
                            }
                        ]
                        if fields.get("youtube_url", "") or fields.get("youtube_label", "")
                        else []
                    ),
                    retained_part_ids=retained,
                    expected_revision=_integer(fields["revision"]),
                    expected_evidence_version=_integer(fields["evidence_version"]),
                )
            elif action == "answer_media_reorder":
                current = services.staff_snapshot(**common)
                parts = [part for part in fields.getlist("parts") if part]
                services.save_multipart_answer(
                    **common,
                    text=current["current_text"],
                    files=[],
                    retained_part_ids=parts,
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
            return _render_staff(request, common, action)
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
        with services.requester_page_projection(
            token=requester_workspace._capability(request), synthetic_fixtures_only=True
        ) as result:
            get_token(request)
            return private(render(request, "answer_media/requester.html", result))
    except (InvalidForm, SuspiciousOperation):
        return denied("answer_media_form_invalid", 400)
    except cases.CaseConflict:
        return denied("private_answer_media_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("answer_media_store_unavailable", 503)


def _file(row):
    if row["kind"] == "YOUTUBE_LINK":
        return private(
            HttpResponse(
                row["raw"],
                content_type="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": 'attachment; filename="youtube-reference.txt"',
                    "Content-Length": str(row["size"]),
                },
            )
        )
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


@protect
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


@protect
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
