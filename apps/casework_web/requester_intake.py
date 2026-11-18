"""Requester receipt adapter using the existing durable intake and browser proof."""
import json
import re
import secrets
from hmac import compare_digest

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.platform_recovery.integration import mutation_service

from .guard import BASE, denied, enabled, private
from .requester_workspace import remember
from .views import FORM_ID_RE, REQUESTER_COOKIE, REQUESTER_SALT, InvalidForm, _form, _requester


def _page(request, *, result=None, question="", error="", code=200):
    get_token(request)
    request_id = secrets.token_hex(16)
    response = render(request, "casework/requester_intake.html", {
        "request_id": request_id,
        "confirmation": browser_proof(request, "casework.intake.v1", request_id),
        "result": result, "question": question, "error": error,
        "intake_attachment_enabled": _attachment_enabled(),
    }, status=code)
    if _requester(request) is None:
        response.set_signed_cookie(
            REQUESTER_COOKIE, "rq_" + secrets.token_hex(16), salt=REQUESTER_SALT,
            httponly=True, samesite="Strict", path=BASE, max_age=86400, secure=False,
        )
    if result and result.get("token"):
        remember(request, response, result["token"])
    return private(response)


def _attachment_enabled():
    return (
        enabled()
        and getattr(settings, "FATWA_BROWSER_AUDIO_ENABLED", False) is True
        and getattr(settings, "FATWA_CASE_ATTACHMENTS_ENABLED", False) is True
    )


def _intake_form(request):
    required = {"question", "request_id", "confirmation"}
    if request.content_type != "multipart/form-data":
        return _form(request, required), None
    fields = request.POST
    if (
        not _attachment_enabled()
        or set(fields) != required | {"csrfmiddlewaretoken", "synthetic_only"}
        or any(len(fields.getlist(key)) != 1 for key in fields)
        or fields["synthetic_only"] != "yes"
        or set(request.FILES) - {"attachment"}
        or len(request.FILES.getlist("attachment")) > 1
    ):
        raise InvalidForm("intake_attachment_form_invalid")
    uploaded = request.FILES.get("attachment")
    if uploaded is None:
        return fields, None
    from apps.case_attachments.services import MAX_BYTES

    if uploaded.size > MAX_BYTES:
        raise InvalidForm("intake_attachment_too_large")
    return fields, dict(
        raw=uploaded.read(MAX_BYTES + 1), filename=uploaded.name, media_type=uploaded.content_type
    )


@mutation_service
def submit_intake(*, question, requester_id, request_id, attachment=None):
    """One canonical intake and optional immutable evidence, or neither.

    The source-event digest pins the exact accepted bytes/name/type to the existing
    intake idempotency key. Replays issue no new capability or evidence. Storage
    locks precede the outer transaction and remain held through its commit.
    """
    common = dict(
        original_question=question, requester_id=requester_id,
        source_event_id="website:" + request_id,
        idempotency_key=request_id, synthetic_fixtures_only=True,
    )
    if attachment is None:
        return services.intake_case(**common)
    if not _attachment_enabled():
        raise services.CaseConflict("intake_attachment_disabled")
    from apps.case_attachments import services as attachments
    from apps.case_attachments.storage_bindings import binding_locks
    from apps.private_media.storage import configured_storage
    from apps.private_media.validation import MediaValidationError

    if type(attachment) is not dict or set(attachment) != {"raw", "filename", "media_type"}:
        raise services.CaseConflict("intake_attachment_invalid")
    media = attachments._validate(**attachment)
    fingerprint = services._digest(json.dumps(
        [media.sha256, media.filename, media.media_type, media.size], ensure_ascii=False
    ))
    common["source_event_id"] += ":" + fingerprint
    try:
        storage = configured_storage()
        with binding_locks(storage, [media.sha256]), synthetic_queue_atomic():
            result = services.intake_case(**common)
            if result["created"]:
                attachments.upload(
                    token=result["token"], expected_revision=result["revision"],
                    synthetic_fixtures_only=True, **attachment,
                )
            return result
    except MediaValidationError as exc:
        raise services.CaseConflict("private_storage_unavailable") from exc


@sensitive_post_parameters("question")
@csrf_protect
def intake(request):
    if request.method in ("GET", "HEAD"):
        return _page(request)
    try:
        fields, attachment = _intake_form(request)
        requester_id = _requester(request)
        if (requester_id is None or FORM_ID_RE.fullmatch(fields["request_id"]) is None
                or re.fullmatch(r"[0-9a-f]{64}", fields["confirmation"]) is None):
            raise InvalidForm("intake_identity_missing")
        if not compare_digest(
            browser_proof(request, "casework.intake.v1", fields["request_id"]),
            fields["confirmation"],
        ):
            return denied("intake_confirmation_invalid", 403)
        question = fields["question"]
        if not question.strip() or len(question) > 16000 or "\x00" in question:
            return _page(request, question=question[:16000], code=400,
                         error="اكتب السؤال من حرف إلى ١٦٠٠٠ حرف دون محارف فارغة غير صالحة.")
        result = submit_intake(
            question=question, requester_id=requester_id,
            request_id=fields["request_id"], attachment=attachment,
        )
        return _page(request, result={
            "public_ref": result["public_ref"], "token": result["token"],
            "created": result["created"],
        })
    except (InvalidForm, SuspiciousOperation):
        return denied("intake_form_invalid", 400)
    except services.CaseConflict:
        return denied("intake_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)
