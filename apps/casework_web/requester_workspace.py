"""Connected requester journey, restricted by the existing synthetic web guard.

The browser holds a short-lived HttpOnly signed capability, never a case selector.
Every read/write reuses the core token service (including revocation and locks).
No requester question, answer, draft or operator event is added to the projection.
"""
import json
import re
from hashlib import sha256
from hmac import compare_digest

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from apps.casework import services
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied

from .guard import BASE, denied, private

URL = BASE + "status/"
COOKIE = "fatwa_casework_private"
SALT = "fatwa.casework.private.v1"
TTL = 15 * 60
TOKEN = re.compile(r"rt_[A-Za-z0-9_-]{43}")
HEX = re.compile(r"[a-f0-9]{64}")
LABELS = {
    "RECEIVED": "تم استلام السؤال",
    "UNDER_REVIEW": "قيد المراجعة",
    "NEEDS_CLARIFICATION": "نحتاج إلى استيضاح",
    "RETURNED_FOR_CHANGES": "قيد المراجعة",
    "ANSWERED": "اكتملت مراجعة الجواب",
}


class InvalidForm(ValueError):
    pass


def _form(request, required):
    if request.content_type != "application/x-www-form-urlencoded":
        raise InvalidForm
    fields = request.POST
    if (set(fields) != set(required) | {"csrfmiddlewaretoken"}
            or any(len(fields.getlist(key)) != 1 for key in fields)):
        raise InvalidForm
    return fields


@sensitive_variables("token")
def _binding(request, token, purpose="session"):
    digest = sha256(token.encode()).hexdigest()
    return browser_proof(request, SALT, purpose + ":" + digest)


@sensitive_variables("token", "values")
def remember(request, response, token):
    """Called only after durable intake or a successful core capability lookup."""
    if type(token) is not str or TOKEN.fullmatch(token) is None:
        raise ValueError("invalid_requester_capability")
    values = {"token": token, "binding": _binding(request, token)}
    response.set_signed_cookie(
        COOKIE, json.dumps(values, separators=(",", ":")), salt=SALT,
        max_age=TTL, httponly=True, samesite="Strict", path=URL, secure=False,
    )
    return response


def forget(response):
    response.delete_cookie(COOKIE, path=URL, samesite="Strict")
    return response


@sensitive_variables("saved", "values", "token")
def _capability(request):
    saved = request.get_signed_cookie(COOKIE, default="", salt=SALT, max_age=TTL)
    try:
        if not isinstance(saved, str) or not 1 <= len(saved) <= 512:
            raise ValueError
        values = json.loads(saved)
        if (type(values) is not dict or set(values) != {"token", "binding"}
                or any(type(value) is not str for value in values.values())
                or TOKEN.fullmatch(values["token"]) is None
                or HEX.fullmatch(values["binding"]) is None
                or not compare_digest(values["binding"], _binding(request, values["token"]))):
            raise ValueError
        return values["token"]
    except (ValueError, TypeError, KeyError, RecursionError):
        raise services.CaseConflict("requester_session_unavailable") from None


@sensitive_variables("token")
def _page(request, *, result=None, token=None, text="", message="", code=200):
    get_token(request)
    proof = None
    if result is not None:
        # A stale tab cannot post to a different case after switching capabilities.
        proof = _binding(request, token, f"followup:{result['public_ref']}:{result['revision']}")
    return private(render(request, "casework/requester_workspace.html", {
        "result": result, "status_label": LABELS.get(
            result["status"], "حالة السؤال تحتاج إلى مراجعة"
        ) if result else "",
        "form_proof": proof, "text": text, "message": message,
    }, status=code))


def _locked(request, message, code=200):
    return forget(_page(request, message=message, code=code))


@sensitive_post_parameters("token", "text")
@sensitive_variables("token", "fields")
@csrf_protect
def workspace(request):
    try:
        if request.method in ("GET", "HEAD"):
            try:
                token = _capability(request)
                result = services.requester_status(token, synthetic_fixtures_only=True)
            except services.CaseConflict:
                return _locked(request, "أدخل رمز الوصول الخاص لفتح المتابعة.")
            return _page(request, result=result, token=token)

        action = request.POST.get("action", "")
        if action == "unlock":
            fields = _form(request, {"action", "token"})
            token = fields["token"]
            try:
                services.requester_status(token, synthetic_fixtures_only=True)
            except services.CaseConflict:
                return _locked(request, "تعذّر فتح المتابعة. تحقق من رمز الوصول أو استخدم إرشادات الاستعادة.", 404)
            return private(remember(request, _redirect(), token))
        if action == "leave":
            _form(request, {"action"})
            # Clear this browser and bind future requests to a fresh CSRF secret.
            # This is not server-side capability revocation; trusted rotation is.
            rotate_token(request)
            return private(forget(_redirect()))
        if action != "followup":
            raise InvalidForm
        fields = _form(request, {"action", "text", "revision", "form_proof"})
        try:
            token = _capability(request)
            result = services.requester_status(token, synthetic_fixtures_only=True)
        except services.CaseConflict:
            return _locked(request, "انتهى الوصول الخاص أو أُبطل. افتح المتابعة مجددًا قبل إرسال التعقيب.", 404)
        revision = fields["revision"]
        if re.fullmatch(r"[1-9][0-9]{0,8}", revision) is None:
            raise InvalidForm
        expected = _binding(request, token, f"followup:{result['public_ref']}:{revision}")
        if (HEX.fullmatch(fields["form_proof"]) is None
                or not compare_digest(expected, fields["form_proof"])):
            # Do not move text from a different case into this case's form.
            return _page(request, result=result, token=token, code=409,
                         message="تغيّرت مساحة المتابعة. افتح القضية المقصودة مجددًا؛ لم يُرسل التعقيب.")
        text = fields["text"]
        if not text.strip() or len(text) > 16000 or "\x00" in text:
            return _page(request, result=result, token=token, text=text[:16000], code=400,
                         message="اكتب تعقيبًا من حرف إلى ١٦٠٠٠ حرف دون محارف فارغة غير صالحة.")
        try:
            services.add_followup(token=token, text=text, expected_revision=int(revision),
                                  synthetic_fixtures_only=True)
        except services.CaseConflict:
            # Recheck access after the write attempt: a concurrent rotation must not
            # leave the old clarification in a response to a revoked capability.
            try:
                result = services.requester_status(token, synthetic_fixtures_only=True)
            except services.CaseConflict:
                return _locked(request, "تعذّر الوصول. افتح المتابعة برمز صالح قبل إعادة المحاولة.", 404)
            message = (
                "تغيّرت القضية ولم يُحفظ التعقيب. راجع الحالة الجديدة والنص ثم أرسله مجددًا."
                if result["revision"] != int(revision)
                else "لم يُحفظ التعقيب. احتفظ بنصه وحاول لاحقًا أو راجع الفريق."
            )
            return _page(request, result=result, token=token, text=text, code=409, message=message)
        # PRG makes browser refresh a read. A repeated old POST fails its revision.
        return private(_redirect())
    except (InvalidForm, SuspiciousOperation):
        return denied("requester_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)


def _redirect():
    return HttpResponse(status=303, headers={"Location": URL})
