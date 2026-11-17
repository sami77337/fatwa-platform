"""Native forms for one durable operational case store; no external sends."""
import re
import secrets
from hmac import compare_digest

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import (
    IdentityUnavailable,
    authenticate_identity,
    require_provider,
    validate_identity,
)

from .access import COOKIE, RequestDirectory, current_staff, set_staff_cookie
from .guard import BASE, denied, private

REQUESTER_COOKIE = "fatwa_casework_requester"
REQUESTER_SALT = "fatwa.casework.requester.v1"
REQUESTER_RE = re.compile(r"rq_[0-9a-f]{32}")
FORM_ID_RE = re.compile(r"[0-9a-f]{32}")
STATUS_LABELS = {
    "RECEIVED": "تم استلام السؤال",
    "UNDER_REVIEW": "قيد المراجعة",
    "NEEDS_CLARIFICATION": "نحتاج إلى استيضاح",
    "WITH_MUFTI": "قيد المراجعة",
    "DRAFTED": "قيد المراجعة",
    "ANSWER_DRAFTED": "قيد المراجعة",
    "PENDING_REVIEW": "قيد المراجعة",
    "RETURNED_FOR_CHANGES": "قيد المراجعة",
    "APPROVED": "اكتملت مراجعة الجواب",
    "ANSWER_APPROVED": "اكتملت مراجعة الجواب",
    "ANSWERED": "اكتملت مراجعة الجواب",
}


class InvalidForm(ValueError):
    pass


def _form(request, required):
    if request.content_type != "application/x-www-form-urlencoded":
        raise InvalidForm("native_form_required")
    fields = request.POST
    if (
        set(fields) != set(required) | {"csrfmiddlewaretoken"}
        or any(len(fields.getlist(key)) != 1 for key in fields)
    ):
        raise InvalidForm("invalid_fields")
    return fields


def _integer(value):
    if type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,8}", value):
        raise InvalidForm("invalid_revision")
    return int(value)


def _provider():
    provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    require_provider(provider)
    return provider


def _requester(request):
    value = request.get_signed_cookie(
        REQUESTER_COOKIE, default="", salt=REQUESTER_SALT, max_age=86400,
    )
    return value if REQUESTER_RE.fullmatch(value) else None


def _intake_page(request, *, result=None):
    get_token(request)
    request_id = secrets.token_hex(16)
    response = render(request, "casework/intake.html", {
        "request_id": request_id,
        "confirmation": browser_proof(request, "casework.intake.v1", request_id),
        "result": result,
    })
    if _requester(request) is None:
        response.set_signed_cookie(
            REQUESTER_COOKIE, "rq_" + secrets.token_hex(16), salt=REQUESTER_SALT,
            httponly=True, samesite="Strict", path=BASE, max_age=86400, secure=False,
        )
    return private(response)


@sensitive_post_parameters("question")
@csrf_protect
def intake(request):
    if request.method in ("GET", "HEAD"):
        return _intake_page(request)
    try:
        fields = _form(request, {"question", "request_id", "confirmation"})
        requester_id = _requester(request)
        if (
            requester_id is None or FORM_ID_RE.fullmatch(fields["request_id"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", fields["confirmation"]) is None
        ):
            raise InvalidForm("intake_identity_missing")
        if not compare_digest(
            browser_proof(request, "casework.intake.v1", fields["request_id"]),
            fields["confirmation"],
        ):
            return denied("intake_confirmation_invalid", 403)
        result = services.intake_case(
            original_question=fields["question"], requester_id=requester_id,
            source_event_id="website:" + fields["request_id"],
            idempotency_key=fields["request_id"], synthetic_fixtures_only=True,
        )
        # No internal PK or requester binding enters the public template context.
        return _intake_page(request, result={
            "public_ref": result["public_ref"], "token": result["token"],
            "created": result["created"],
        })
    except (InvalidForm, SuspiciousOperation):
        return denied("intake_form_invalid", 400)
    except services.CaseConflict:
        return denied("intake_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


def _status_page(request, result=None):
    get_token(request)
    return private(render(request, "casework/status.html", {
        "result": result,
        "status_label": STATUS_LABELS.get(
            result["status"], "حالة السؤال تحتاج إلى مراجعة"
        ) if result else "",
    }))


@sensitive_post_parameters("token")
@csrf_protect
def status(request):
    if request.method in ("GET", "HEAD"):
        return _status_page(request)
    try:
        fields = _form(request, {"token"})
        result = services.requester_status(fields["token"], synthetic_fixtures_only=True)
        return _status_page(request, result)
    except (InvalidForm, SuspiciousOperation):
        return denied("requester_form_invalid", 400)
    except services.CaseConflict:
        return denied("requester_access_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


@sensitive_post_parameters("token", "text")
@csrf_protect
def followup(request):
    try:
        fields = _form(request, {"token", "text", "revision"})
        result = services.add_followup(
            token=fields["token"], text=fields["text"],
            expected_revision=_integer(fields["revision"]), synthetic_fixtures_only=True,
        )
        return _status_page(request, result)
    except (InvalidForm, SuspiciousOperation):
        return denied("requester_form_invalid", 400)
    except services.CaseConflict:
        return denied("requester_update_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


@sensitive_post_parameters("credential")
@csrf_protect
def staff_login(request):
    if request.method in ("GET", "HEAD"):
        get_token(request)
        return private(render(request, "casework/login.html"))
    try:
        fields = _form(request, {"credential"})
        provider = _provider()
        identity = authenticate_identity(provider, fields["credential"])
        rotate_token(request)
        response = HttpResponse(status=303, headers={"Location": BASE + "staff/"})
        return private(set_staff_cookie(request, response, provider, identity))
    except (InvalidForm, SuspiciousOperation):
        return denied("staff_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)


@csrf_protect
def staff_logout(request):
    try:
        _form(request, set())
    except (InvalidForm, SuspiciousOperation):
        return denied("staff_form_invalid", 400)
    rotate_token(request)
    response = HttpResponse(status=303, headers={"Location": BASE + "staff/login/"})
    response.delete_cookie(COOKIE, path=BASE, samesite="Strict")
    return private(response)


def _staff_context(request, provider, identity, *, selected=None, access=None):
    rows = services.list_cases(
        subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True,
    )
    get_token(request)
    return private(render(request, "casework/staff.html", {
        "cases": rows, "selected": selected, "access": access,
    }))


@sensitive_post_parameters("text", "note")
@csrf_protect
def staff(request):
    try:
        provider = _provider()
        authenticated_provider_id = provider.provider_id
        identity = current_staff(request, provider)
        provider = RequestDirectory(
            provider, identity, authenticated_provider_id=authenticated_provider_id,
        )
        if request.method in ("GET", "HEAD"):
            return _staff_context(request, provider, identity)
        # Read only the action to select an exact allowed shape; no actor or role is accepted.
        action = request.POST.get("action", "")
        required = {"action", "case_ref"}
        if action in {"draft", "clarify"}:
            required |= {"text", "revision", "evidence_version"}
        elif action in {"approve", "return"}:
            required |= {"answer_id", "note", "revision", "evidence_version"}
        elif action not in {"open", "rotate", "revoke"}:
            raise InvalidForm("unknown_action")
        fields = _form(request, required)
        validate_identity(identity, case_key=fields["case_ref"])
        # Resolve internal ID from an already scoped server read. A guessed FT ref grants nothing.
        rows = services.list_cases(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True,
        )
        row = next((item for item in rows if item["public_ref"] == fields["case_ref"]), None)
        if row is None:
            return denied("staff_case_unavailable", 404)
        common = {
            "case_id": row["case_id"], "subject_id": identity.subject_id,
            "provider": provider, "synthetic_fixtures_only": True,
        }
        access = None
        if action == "open":
            selected = services.read_case(**common)
        elif action in {"draft", "clarify", "approve", "return"}:
            current = {
                **common, "expected_revision": _integer(fields["revision"]),
                "expected_evidence_version": _integer(fields["evidence_version"]),
            }
            if action == "draft":
                selected = services.save_answer(**current, text=fields["text"])
            elif action == "clarify":
                selected = services.request_clarification(**current, text=fields["text"])
            else:
                selected = services.record_decision(
                    **current, answer_id=fields["answer_id"], note=fields["note"],
                    action="APPROVE" if action == "approve" else "RETURN_FOR_CHANGES",
                )
        else:
            resolver = getattr(settings, "FATWA_CASEWORK_RECOVERY_RESOLVER", None)
            if not callable(resolver):
                return denied("trusted_recovery_unavailable", 503)
            try:
                requester_id = resolver(identity.subject_id, fields["case_ref"])
            except Exception:
                return denied("trusted_recovery_unavailable", 503)
            method = services.rotate_access if action == "rotate" else services.revoke_access
            result = method(**common, requester_id=requester_id)
            access = {"token": result.get("token"), "rotated": action == "rotate"}
            selected = services.read_case(**common)
        return _staff_context(request, provider, identity, selected=selected, access=access)
    except (InvalidForm, SuspiciousOperation):
        return denied("staff_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except services.CaseConflict:
        return denied("staff_update_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


def stylesheet(request):
    from .styles import CSS
    return private(HttpResponse(CSS, content_type="text/css; charset=utf-8"))
