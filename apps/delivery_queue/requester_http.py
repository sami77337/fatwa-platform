"""Privacy-preserving requester tracking, opt-in loopback synthetic UI only."""
from __future__ import annotations

import os

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from .requester_tracking import TrackingDenied, lookup_case_status

BASE = "/requester/tracking/"
_STATUS_LABELS = {
    "RECEIVED": "تم استلام السؤال",
    "UNDER_REVIEW": "قيد المراجعة",
    "NEEDS_CLARIFICATION": "نحتاج إلى استيضاح",
    "WITH_MUFTI": "معروض للمراجعة الشرعية",
    "RETURNED_FOR_CHANGES": "أُعيد للمؤلف للتعديل",
    "PREPARING_DELIVERY": "يجري تجهيز الجواب",
    "DELIVERY_IN_PROGRESS": "تجري متابعة التسليم مع القناة",
    "PARTIALLY_REPORTED": "أبلغت القناة عن وصول بعض الأجزاء",
    "PROVIDER_REPORTED_DELIVERY_UNVERIFIED": "أبلغت القناة عن التسليم، والإثبات غير متحقق",
    "DELIVERY_NEEDS_RECONCILIATION": "حالة التسليم تحتاج إلى مراجعة",
    "DELIVERY_REQUIRES_REVIEW": "تعذّر التسليم ويلزم تدخل المشغّل",
}

CSS = """body{margin:0;background:#f4f6f9;color:#182638;font:18px/1.75 system-ui,sans-serif}
main,header{max-width:780px;margin:auto;padding:1.1rem;box-sizing:border-box}
h1{font-size:1.65rem;line-height:1.4}
form,article{background:white;border:1px solid #d1d8e1;border-radius:10px;margin:1rem 0;padding:1rem}
label{display:block}input,button{font:inherit;padding:.55rem;max-width:100%;box-sizing:border-box}
input[type=password]{width:100%;direction:ltr}button{cursor:pointer}
a:focus,button:focus,input:focus{outline:3px solid #9c6800;outline-offset:3px}
.notice{border-right:4px solid #9c6800;padding:.6rem}
bdi{overflow-wrap:anywhere}
@media(max-width:480px){main,header{padding:.65rem}form,article{padding:.75rem}}"""


def _private(response, *, head=False):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Vary"] = "Cookie"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    if head:
        response.content = b""
    return response


def _denied(code, status):
    return _private(JsonResponse({"error": code}, status=status))


def _enabled():
    return (
        os.environ.get("FATWA_PRODUCTION") == "0"
        and getattr(settings, "FATWA_REQUESTER_TRACKING_ENABLED", False) is True
    )


@sensitive_post_parameters("token")
@csrf_protect
def portal(request):
    if not _enabled():
        return _denied("tracking_disabled", 503)
    if request.GET:
        return _denied("query_tokens_not_supported", 400)
    if request.method not in ("GET", "HEAD", "POST"):
        return _denied("tracking_method_not_supported", 405)
    if request.method in ("GET", "HEAD"):
        get_token(request)
        return _private(
            render(request, "delivery_queue/requester_tracking.html", {}),
            head=request.method == "HEAD",
        )
    if request.content_type != "application/x-www-form-urlencoded":
        return _denied("tracking_form_invalid", 400)
    fields = request.POST
    if (
        set(fields) != {"csrfmiddlewaretoken", "token"}
        or any(len(fields.getlist(key)) != 1 for key in fields)
        or len(fields.get("token", "")) > 128
    ):
        return _denied("tracking_form_invalid", 400)
    try:
        result = lookup_case_status(fields["token"])
    except TrackingDenied:
        return _denied("tracking_token_invalid_or_expired", 404)
    return _private(render(
        request, "delivery_queue/requester_tracking.html",
        {"status": result, "status_label": _STATUS_LABELS.get(
            result["status"], "حالة السؤال تحتاج إلى مراجعة",
        )},
    ))


def stylesheet(request):
    if not _enabled():
        return _denied("tracking_disabled", 503)
    if request.method not in ("GET", "HEAD"):
        return _denied("tracking_method_not_supported", 405)
    if request.GET:
        return _denied("query_tokens_not_supported", 400)
    return _private(
        HttpResponse(CSS, content_type="text/css; charset=utf-8"),
        head=request.method == "HEAD",
    )


class RequesterTrackingGuard:
    """No Internet routes, unknown paths, or privileged mutations."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _enabled():
            return _denied("tracking_disabled", 503)
        if request.META.get("REMOTE_ADDR") not in ("127.0.0.1", "::1"):
            return _denied("loopback_training_only", 403)
        methods = {
            BASE: ("GET", "HEAD", "POST"),
            BASE + "tracking.css": ("GET", "HEAD"),
        }
        if request.path not in methods:
            return _denied("tracking_not_found", 404)
        if request.method not in methods[request.path]:
            response = _denied("tracking_method_not_supported", 405)
            response["Allow"] = ", ".join(methods[request.path])
            return response
        try:
            length = int(request.META.get("CONTENT_LENGTH") or "0")
        except (TypeError, ValueError):
            return _denied("tracking_form_invalid", 400)
        if length < 0 or length > 4096:
            return _denied("tracking_form_too_large", 413)
        return _private(self.get_response(request), head=request.method == "HEAD")
