"""Requester receipt adapter using the existing durable intake and browser proof."""
import re
import secrets
from hmac import compare_digest

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied

from .guard import BASE, denied, private
from .requester_workspace import remember
from .views import FORM_ID_RE, REQUESTER_COOKIE, REQUESTER_SALT, InvalidForm, _form, _requester


def _page(request, *, result=None, question="", error="", code=200):
    get_token(request)
    request_id = secrets.token_hex(16)
    response = render(request, "casework/requester_intake.html", {
        "request_id": request_id,
        "confirmation": browser_proof(request, "casework.intake.v1", request_id),
        "result": result, "question": question, "error": error,
    }, status=code)
    if _requester(request) is None:
        response.set_signed_cookie(
            REQUESTER_COOKIE, "rq_" + secrets.token_hex(16), salt=REQUESTER_SALT,
            httponly=True, samesite="Strict", path=BASE, max_age=86400, secure=False,
        )
    if result and result.get("token"):
        remember(request, response, result["token"])
    return private(response)


@sensitive_post_parameters("question")
@csrf_protect
def intake(request):
    if request.method in ("GET", "HEAD"):
        return _page(request)
    try:
        fields = _form(request, {"question", "request_id", "confirmation"})
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
        result = services.intake_case(
            original_question=question, requester_id=requester_id,
            source_event_id="website:" + fields["request_id"],
            idempotency_key=fields["request_id"], synthetic_fixtures_only=True,
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
