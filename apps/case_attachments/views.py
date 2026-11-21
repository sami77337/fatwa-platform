"""Attachment forms reuse existing scoped staff sessions and private requester cookies."""

from hmac import compare_digest

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from apps.casework import services as cases
from apps.casework_web import requester_workspace as workspace
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, validate_identity
from apps.private_media import links

from . import services

REQUESTER_ACTIONS = frozenset(
    {"attachments", "attachment_upload", "attachment_preview", "attachment_download"}
)
STAFF_ACTIONS = frozenset({"attachment_list", "attachment_preview", "attachment_download"})


def _page(request, result, *, token=None, is_staff=False, preview=None):
    get_token(request)
    return private(
        render(
            request,
            "case_attachments/desk.html",
            {
                "result": result,
                "is_staff": is_staff,
                "preview": preview,
                "video_upload_enabled": getattr(settings, "FATWA_CASE_ATTACHMENTS_VIDEO_ENABLED", False) is True,
                "upload_proof": workspace._binding(
                    request, token, f"attachment:{result['public_ref']}:{result['revision']}"
                )
                if token
                else None,
            },
        )
    )


def _download(row, request, *, is_staff):
    if links.enabled():
        audience = "staff" if is_staff else "status"
        url = links.issue(
            request, f"/casework/{audience}/attachments/{row['id']}/", purpose="DOWNLOAD"
        )
        return private(HttpResponse(status=303, headers={"Location": url}))
    return private(
        HttpResponse(
            row["raw"],
            content_type=row["media_type"],
            headers={
                "Content-Disposition": f'attachment; filename="{row["filename"]}"',
            },
        )
    )


def _multipart(request):
    fields = request.POST
    if (
        request.content_type != "multipart/form-data"
        or set(fields)
        != {"action", "revision", "upload_proof", "synthetic_only", "csrfmiddlewaretoken"}
        or any(len(fields.getlist(k)) != 1 for k in fields)
        or set(request.FILES) != {"attachment"}
        or len(request.FILES.getlist("attachment")) != 1
        or fields["synthetic_only"] != "yes"
    ):
        raise InvalidForm("attachment_form_invalid")
    return fields


@sensitive_post_parameters()
@sensitive_variables("token", "fields", "row")
@csrf_protect
def requester(request):
    if request.method != "POST" or request.POST.get("action") not in REQUESTER_ACTIONS:
        from apps.requester_access_review.views import requester as campaign_requester

        return campaign_requester(request)
    try:
        token = workspace._capability(request)
        action = request.POST.get("action")
        required = {"action"} if action == "attachments" else {"action", "attachment_id"}
        fields = _multipart(request) if action == "attachment_upload" else _form(request, required)
        result = services.requester_list(token=token, synthetic_fixtures_only=True)
        preview = None
        if action == "attachment_upload":
            proof = workspace._binding(
                request, token, f"attachment:{result['public_ref']}:{fields['revision']}"
            )
            if not compare_digest(proof, fields["upload_proof"]):
                return denied("attachment_form_changed", 409)
            uploaded = request.FILES["attachment"]
            if uploaded.size > services.MAX_BYTES:
                return denied("attachment_too_large", 413)
            services.upload(
                token=token,
                raw=uploaded.read(services.MAX_BYTES + 1),
                filename=uploaded.name,
                media_type=uploaded.content_type,
                expected_revision=_integer(fields["revision"]),
                synthetic_fixtures_only=True,
            )
            result = services.requester_list(token=token, synthetic_fixtures_only=True)
        elif action in {"attachment_preview", "attachment_download"}:
            row = services.requester_read(
                token=token,
                attachment_id=fields["attachment_id"],
                synthetic_fixtures_only=True,
            )
            if action == "attachment_download":
                return _download(row, request, is_staff=False)
            preview = _preview(row, is_staff=False)
        return _page(request, result, token=token, preview=preview)
    except (InvalidForm, SuspiciousOperation):
        return denied("attachment_form_invalid", 400)
    except cases.CaseConflict:
        return denied("attachment_unavailable_or_stale", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


@sensitive_post_parameters()
@csrf_protect
def staff(request):
    if request.method != "POST" or request.POST.get("action") not in STAFF_ACTIONS:
        from apps.requester_team_journey.views import staff as campaign_staff

        return campaign_staff(request)
    try:
        provider = _provider()
        actor = current_staff(request, provider)
        provider = RequestDirectory(provider, actor, authenticated_provider_id=provider.provider_id)
        action = request.POST.get("action")
        required = {"action", "case_ref"}
        if action != "attachment_list":
            required.add("attachment_id")
        fields = _form(request, required)
        validate_identity(actor, case_key=fields["case_ref"])
        rows = cases.list_cases(
            subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        selected = next((r for r in rows if r["public_ref"] == fields["case_ref"]), None)
        if selected is None:
            return denied("attachment_unavailable", 404)
        common = {
            "case_id": selected["case_id"],
            "subject_id": actor.subject_id,
            "provider": provider,
            "synthetic_fixtures_only": True,
        }
        result = services.staff_list(**common)
        preview = None
        if action in {"attachment_preview", "attachment_download"}:
            row = services.staff_read(**common, attachment_id=fields["attachment_id"])
            if action == "attachment_download":
                return _download(row, request, is_staff=True)
            preview = _preview(row, is_staff=True)
        return _page(request, result, is_staff=True, preview=preview)
    except (InvalidForm, SuspiciousOperation):
        return denied("attachment_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("attachment_unavailable_or_stale", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


def _preview(row, *, is_staff):
    audience = "staff" if is_staff else "status"
    return {
        **row,
        "text": row["raw"].decode("utf-8") if row["kind"] == "text" else "",
        "media_url": f"/casework/{audience}/attachments/{row['id']}/",
    }


def _inline(row):
    response = private(
        HttpResponse(
            row["raw"],
            content_type=row["media_type"],
            headers={
                "Content-Disposition": f'inline; filename="{row["filename"]}"',
            },
        )
    )
    response["Content-Security-Policy"] = "sandbox; default-src 'none'; frame-ancestors 'self'"
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


@links.protect
@sensitive_variables("token", "row")
def requester_file(request, attachment_id):
    if request.method not in {"GET", "HEAD"} or request.GET:
        return denied("attachment_unavailable", 404)
    try:
        token = workspace._capability(request)
        row = services.requester_read(
            token=token, attachment_id=attachment_id, synthetic_fixtures_only=True
        )
        return _inline(row)
    except (cases.CaseConflict, InvalidForm, SuspiciousOperation):
        return denied("attachment_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


@links.protect
def staff_file(request, attachment_id):
    if request.method not in {"GET", "HEAD"} or request.GET:
        return denied("attachment_unavailable", 404)
    try:
        from .models import CaseAttachment

        provider = _provider()
        actor = current_staff(request, provider)
        provider = RequestDirectory(provider, actor, authenticated_provider_id=provider.provider_id)
        case_id = (
            CaseAttachment.objects.filter(pk=attachment_id)
            .values_list("case_id", flat=True)
            .first()
        )
        if case_id is None:
            raise cases.CaseConflict("attachment_unavailable")
        row = services.staff_read(
            case_id=case_id,
            subject_id=actor.subject_id,
            provider=provider,
            attachment_id=attachment_id,
            synthetic_fixtures_only=True,
        )
        return _inline(row)
    except (cases.CaseConflict, IdentityUnavailable, InvalidForm, SuspiciousOperation):
        return denied("attachment_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)
