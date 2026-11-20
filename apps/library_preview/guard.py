"""Loopback-only read boundary; public-looking preview is never internet publishing."""

import re
from functools import wraps

from django.core.exceptions import DisallowedHost
from django.db import DatabaseError
from django.http import HttpResponse

from apps.casework_web.guard import CaseworkGuard
from apps.intake_workflow.guards import SyntheticWriteDenied

from . import services

BASE = "/library-preview/"


def private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    if getattr(response, "_allow_library_media", False) is True:
        response["Content-Security-Policy"] += "; media-src 'self'; img-src 'self'"
    if getattr(response, "_allow_library_offline", False) is True:
        response["Content-Security-Policy"] += (
            "; script-src 'self'; worker-src 'self'; connect-src 'self'; "
            "manifest-src 'self'; media-src 'self' blob:; img-src 'self' blob:"
        )
    response["X-Frame-Options"] = "DENY"
    return response


def denied(status=404):
    return private(
        HttpResponse("المعاينة غير متاحة", status=status, content_type="text/plain; charset=utf-8")
    )


def boundary(request):
    try:
        services.policy()
    except services.PreviewUnavailable:
        return denied()
    if request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}:
        return denied(403)
    try:
        host = request.get_host()
    except DisallowedHost:
        return denied(400)
    if re.fullmatch(r"(?:127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", host) is None or any(
        key in request.META
        for key in ("HTTP_FORWARDED", "HTTP_X_FORWARDED_HOST", "HTTP_X_FORWARDED_FOR")
    ):
        return denied(403)
    if request.method not in {"GET", "HEAD"}:
        response = denied(405)
        response["Allow"] = "GET, HEAD"
        return response
    if len(request.META.get("QUERY_STRING", "")) > 2048:
        return denied(400)
    return None


def safe_read(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        refused = boundary(request)
        if refused is not None:
            return refused
        try:
            response = view(request, *args, **kwargs)
        except services.InvalidFilter:
            response = denied(400)
        except services.PreviewUnavailable:
            response = denied()
        except (DatabaseError, SyntheticWriteDenied):
            response = denied(503)
        if request.method == "HEAD":
            response.content = b""
        return private(response)

    return wrapped


class PreviewCompositionGuard:
    """Replace CaseworkGuard in synthetic composition, preserving it elsewhere.

    Only this prefix gets this read-only boundary; casework/staff/private-media
    routes still execute the original guard unchanged. Views repeat the boundary
    so including their URLconf without this wrapper cannot expose them remotely.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.casework = CaseworkGuard(get_response)

    def __call__(self, request):
        if not request.path.startswith(BASE):
            return self.casework(request)
        refused = boundary(request)
        if refused is not None:
            return refused
        return private(self.get_response(request))
