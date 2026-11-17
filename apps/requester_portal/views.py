"""Native forms on the existing private status route and capability cookie."""

from hmac import compare_digest

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from apps.case_attachments import services as attachments
from apps.case_attachments.views import _multipart
from apps.casework import services as cases
from apps.casework_web import requester_workspace as workspace
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.requester_access_review import services as access

from . import services

URL = workspace.URL


def _redirect():
    return private(HttpResponse(status=303, headers={"Location": URL}))


@sensitive_variables("token")
def _page(request, *, token=None, result=None, text="", message="", status=200):
    get_token(request)
    context = {"result": result, "text": text, "message": message}
    if result:
        for name, purpose in (("form_proof", "followup"), ("upload_proof", "attachment")):
            context[name] = workspace._binding(
                request, token, f"{purpose}:{result['public_ref']}:{result['revision']}"
            )
        context["review_proof"] = workspace._binding(
            request, token, "access-review:" + result["public_ref"]
        )
    return private(render(request, "requester_portal/portal.html", context, status=status))


def _locked(request, status=200):
    return workspace.forget(
        _page(
            request,
            status=status,
            message="أدخل رمز الوصول الخاص لفتح قضيتك. رقم القضية وحده لا يمنح الوصول.",
        )
    )


def _read(token):
    return services.snapshot(token=token, synthetic_fixtures_only=True)


def _proof(request, token, result, purpose, revision, submitted):
    expected = workspace._binding(request, token, f"{purpose}:{result['public_ref']}:{revision}")
    return len(submitted) == 64 and compare_digest(expected, submitted)


@sensitive_post_parameters()
@sensitive_variables("token", "fields")
@csrf_protect
def portal(request):
    try:
        services.enabled()
        if request.GET:
            raise InvalidForm("portal_query_not_supported")
        if request.method in {"GET", "HEAD"}:
            try:
                token = workspace._capability(request)
                result = _read(token)
            except cases.CaseConflict:
                return _locked(request)
            return _page(request, token=token, result=result)
        if request.method != "POST":
            return denied("portal_method_invalid", 405)
        action = request.POST.get("action", "")
        if action == "unlock":
            fields = _form(request, {"action", "token"})
            cases.requester_status(fields["token"], synthetic_fixtures_only=True)
            return workspace.remember(request, _redirect(), fields["token"])
        if action == "leave":
            _form(request, {"action"})
            rotate_token(request)
            return workspace.forget(_redirect())
        if action == "trusted_recover":
            from apps.requester_access_review.views import requester

            return requester(request)
        token = workspace._capability(request)
        result = _read(token)
        if action == "followup":
            fields = _form(request, {"action", "revision", "form_proof", "text"})
            revision = _integer(fields["revision"])
            if not _proof(request, token, result, "followup", revision, fields["form_proof"]):
                return _page(
                    request,
                    token=token,
                    result=result,
                    status=409,
                    message="تغيرت القضية أو الجلسة؛ لم يُرسل النص إلى قضية أخرى.",
                )
            text = fields["text"]
            try:
                cases._text(text)
            except cases.CaseConflict:
                return _page(
                    request,
                    token=token,
                    result=result,
                    text=text[:16000],
                    status=400,
                    message="اكتب تعقيبًا من حرف إلى ١٦٠٠٠ حرف دون محارف غير صالحة.",
                )
            try:
                cases.add_followup(
                    token=token, text=text, expected_revision=revision, synthetic_fixtures_only=True
                )
            except cases.CaseConflict:
                return _page(
                    request,
                    token=token,
                    result=_read(token),
                    text=text,
                    status=409,
                    message="تغيرت القضية ولم يُحفظ التعقيب؛ راجع الحالة والنص ثم أعد الإرسال.",
                )
        elif action == "attachment_upload":
            fields = _multipart(request)
            revision = _integer(fields["revision"])
            if not _proof(request, token, result, "attachment", revision, fields["upload_proof"]):
                return denied("portal_attachment_context_changed", 409)
            uploaded = request.FILES["attachment"]
            if uploaded.size > attachments.MAX_BYTES:
                return denied("portal_attachment_too_large", 413)
            try:
                attachments.upload(
                    token=token,
                    raw=uploaded.read(attachments.MAX_BYTES + 1),
                    filename=uploaded.name,
                    media_type=uploaded.content_type,
                    expected_revision=revision,
                    synthetic_fixtures_only=True,
                )
            except cases.CaseConflict:
                return _page(
                    request,
                    token=token,
                    result=_read(token),
                    status=409,
                    message="لم يُحفظ المرفق؛ راجع حداثة القضية ونوع الملف وحجمه، وأجب عن الاستيضاح إن وجد.",
                )
        elif action == "request_access_review":
            fields = _form(request, {"action", "reason", "review_proof"})
            expected = workspace._binding(request, token, "access-review:" + result["public_ref"])
            if not compare_digest(expected, fields["review_proof"]):
                raise InvalidForm("access_review_context_changed")
            access.request_review(
                token=token,
                reason=fields["reason"],
                expected_case_ref=result["public_ref"],
                synthetic_fixtures_only=True,
            )
        else:
            raise InvalidForm("portal_action_invalid")
        return _redirect()
    except (InvalidForm, workspace.InvalidForm, SuspiciousOperation):
        return denied("portal_form_invalid", 400)
    except cases.CaseConflict:
        return _locked(request, status=404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("portal_store_unavailable", 503)
