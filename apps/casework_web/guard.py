"""Closed synthetic web profile with PostgreSQL-backed request budgets."""
import os
import re
import time
from hashlib import sha256

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.db import DatabaseError, connection, transaction
from django.http import JsonResponse

from apps.intake_workflow.guards import SyntheticWriteDenied, require_owned_database
from apps.platform_recovery.integration import MaintenanceUnavailable, require_admission

from .models import ThrottleBucket

BASE = "/casework/"
ROUTES = {
    "/research-workspace.css": ("GET", "HEAD"),
    BASE: ("GET", "HEAD", "POST"),
    BASE + "status/": ("GET", "HEAD", "POST"),
    BASE + "followup/": ("POST",),
    BASE + "staff/login/": ("GET", "HEAD", "POST"),
    BASE + "staff/": ("GET", "HEAD", "POST"),
    BASE + "staff/quality/": ("GET", "HEAD"),
    BASE + "staff/logout/": ("POST",),
    BASE + "operations/": ("GET", "HEAD", "POST"),
    BASE + "operations/login/": ("GET", "HEAD", "POST"),
    BASE + "operations/logout/": ("POST",),
    BASE + "sessions/": ("GET", "HEAD", "POST"),
    BASE + "operations/sessions/": ("GET", "HEAD", "POST"),
    BASE + "ai-citations/": ("POST",),
    BASE + "ai-citations/panel.mjs": ("GET", "HEAD"),
    BASE + "staff/recording-player.js": ("GET", "HEAD"),
    BASE + "staff/answer-media/related.mjs": ("GET", "HEAD"),
    BASE + "staff/pwa/manifest.webmanifest": ("GET", "HEAD"),
    BASE + "staff/pwa/install.mjs": ("GET", "HEAD"),
    BASE + "staff/pwa/sw.mjs": ("GET", "HEAD"),
    BASE + "staff/pwa/icon-192.png": ("GET", "HEAD"),
    BASE + "staff/pwa/icon-512.png": ("GET", "HEAD"),
    BASE + "casework.css": ("GET", "HEAD"),
    BASE + "audio-capture.js": ("GET", "HEAD"),
    BASE + "audio-worklet.js": ("GET", "HEAD"),
    BASE + "audio-capture.css": ("GET", "HEAD"),
}
PRIVATE_MEDIA_ROUTE = re.compile(
    r"/casework/(?:staff|status)/(?:attachments|answer-media)/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
)
LIBRARY_MEDIA_ROUTE = re.compile(
    r"/casework/staff/library/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/(?:file|download)/"
)
RECORDING_MEDIA_ROUTE = re.compile(
    r"/casework/staff/(?:recording-parts|recording-transcripts)/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/audio/"
)
RECORDING_SEGMENT_ROUTE = re.compile(
    r"/casework/staff/recording-transcripts/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/segments/[0-5]/"
)
PRECISE_CITATION_ROUTE = re.compile(
    r"/casework/precise-citations/(?:sources|print|export)/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
)
PRECISE_CITATION_FILE_ROUTE = re.compile(
    r"/casework/precise-citations/sources/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/file/"
)
TIMED_MEDIA_ROUTE = re.compile(
    r"/casework/staff/timed-citations/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"(?:audio|review-audio)/"
)
PDF_MEDIA_ROUTE = re.compile(
    r"/casework/staff/pdf-citations/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"(?:document|review-document|page|review-page)/"
)
LIMITS = {"read": 150, "intake": 10, "login": 10, "requester": 30, "staff": 60}


def enabled():
    return (
        os.environ.get("FATWA_PRODUCTION") == "0"
        and getattr(settings, "FATWA_CASEWORK_WEB_ENABLED", False) is True
    )


def private(response, *, head=False):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Vary"] = "Cookie"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.setdefault("Content-Security-Policy", (
        "default-src 'none'; style-src 'self'; form-action 'self'; "
        "img-src 'self'; media-src 'self'; frame-src 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ))
    # Only the server-rendered native recorder opts this HTML response into the
    # microphone. Private original byte responses and custom sandbox CSPs retain
    # their policy; user text is escaped by these templates, never trusted markup.
    if (
        enabled()
        and getattr(settings, "FATWA_BROWSER_AUDIO_ENABLED", False) is True
        and response.status_code == 200
        and response.get("Content-Type", "").startswith("text/html")
        and not getattr(response, "streaming", False)
        and b'<fieldset data-browser-audio data-input-name="' in response.content
        and "sandbox" not in response["Content-Security-Policy"]
    ):
        policy = response["Content-Security-Policy"]
        if "script-src" not in policy:
            response["Content-Security-Policy"] = (
                policy.replace("media-src 'self';", "media-src 'self' blob:;")
                + "; script-src 'self'; worker-src 'self'"
            )
        response["Permissions-Policy"] = "microphone=(self), camera=()"
    if (
        enabled()
        and getattr(settings, "FATWA_STAFF_PWA_ENABLED", False) is True
        and response.status_code == 200
        and response.get("Content-Type", "").startswith("text/html")
        and not getattr(response, "streaming", False)
        and b'data-staff-pwa="enabled"' in response.content
        and "sandbox" not in response["Content-Security-Policy"]
    ):
        policy = response["Content-Security-Policy"]
        for directive in ("script-src", "worker-src", "manifest-src"):
            if directive not in policy:
                policy += "; " + directive + " 'self'"
        response["Content-Security-Policy"] = policy
    if (
        enabled()
        and getattr(settings, "FATWA_PUBLIC_ANSWER_MEDIA_ENABLED", False) is True
        and getattr(response, "_allow_recording_player", False) is True
        and response.status_code == 200
        and response.get("Content-Type", "").startswith("text/html")
        and "sandbox" not in response["Content-Security-Policy"]
    ):
        policy = response["Content-Security-Policy"]
        if "script-src" not in policy:
            response["Content-Security-Policy"] = policy + "; script-src 'self'"
    if (
        enabled()
        and getattr(settings, "FATWA_ANSWER_RELATED_ENABLED", False) is True
        and response.status_code == 200
        and response.get("Content-Type", "").startswith("text/html")
        and not getattr(response, "streaming", False)
        and b'data-answer-related="enabled"' in response.content
        and "sandbox" not in response["Content-Security-Policy"]
    ):
        policy = response["Content-Security-Policy"]
        for directive in ("script-src", "connect-src"):
            if directive not in policy:
                policy += "; " + directive + " 'self'"
        response["Content-Security-Policy"] = policy
    if head:
        response.content = b""
    return response


def denied(code, status):
    return private(JsonResponse({"error": code}, status=status))


def _budget(request):
    # Even GET consumes a durable budget. A strict composition missing the outer
    # maintenance middleware must fail before opening this native transaction.
    require_admission()
    group = "read"
    if request.method == "POST":
        if request.path == BASE:
            group = "intake"
        elif request.path in {
            BASE + "staff/login/",
            BASE + "operations/login/",
            BASE + "sessions/",
            BASE + "operations/sessions/",
        }:
            # Session forms can actively verify a credential. Charge every POST
            # to the existing login budget without parsing an untrusted body.
            group = "login"
        elif "/staff/" in request.path or request.path.startswith(BASE + "operations/"):
            group = "staff"
        else:
            group = "requester"
    # REMOTE_ADDR has already been restricted to two literal loopback addresses.
    # Forwarded headers and capabilities never participate in keys or diagnostics.
    key = sha256((request.META["REMOTE_ADDR"] + "|" + group).encode()).hexdigest()
    window = int(time.time()) // 60
    require_owned_database(synthetic_fixtures_only=True)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 209))", [key])
        bucket = ThrottleBucket.objects.filter(pk=key).first()
        if bucket is None:
            ThrottleBucket.objects.create(key=key, window=window, requests=1)
        elif bucket.window != window:
            bucket.window, bucket.requests = window, 1
            bucket.save(update_fields=["window", "requests"])
        elif bucket.requests >= LIMITS[group]:
            return False
        else:
            bucket.requests += 1
            bucket.save(update_fields=["requests"])
    return True


class CaseworkGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not enabled():
            return denied("casework_disabled", 503)
        if request.META.get("REMOTE_ADDR") not in ("127.0.0.1", "::1"):
            return denied("loopback_training_only", 403)
        try:
            host = request.get_host()
        except DisallowedHost:
            return denied("casework_host_invalid", 400)
        # Validate GET as well as POST: ALLOWED_HOSTS is enforced only when
        # get_host() runs. Literal loopback hosts also close DNS-rebinding access.
        if re.fullmatch(r"(?:127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", host) is None:
            return denied("casework_host_invalid", 400)
        methods = ROUTES.get(request.path)
        if request.path in {BASE + "staff/privacy/", BASE + "operations/privacy/"}:
            methods = (
                ("GET", "POST")
                if getattr(settings, "FATWA_DATA_PRIVACY_ENABLED", False) is True
                else None
            )
        if methods is None and (
            PRIVATE_MEDIA_ROUTE.fullmatch(request.path)
            or LIBRARY_MEDIA_ROUTE.fullmatch(request.path)
            or PRECISE_CITATION_ROUTE.fullmatch(request.path)
            or PRECISE_CITATION_FILE_ROUTE.fullmatch(request.path)
            or RECORDING_MEDIA_ROUTE.fullmatch(request.path)
            or RECORDING_SEGMENT_ROUTE.fullmatch(request.path)
            or TIMED_MEDIA_ROUTE.fullmatch(request.path)
            or PDF_MEDIA_ROUTE.fullmatch(request.path)
        ):
            methods = ("GET", "HEAD")
        if methods is None:
            return denied("casework_not_found", 404)
        if request.method not in methods:
            response = denied("casework_method_not_supported", 405)
            response["Allow"] = ", ".join(methods)
            return response
        if request.META.get("QUERY_STRING"):
            from apps.private_media.links import admits_query

            if not admits_query(request):
                return denied("casework_query_not_supported", 400)
        try:
            length = int(request.META.get("CONTENT_LENGTH") or "0")
        except (TypeError, ValueError):
            return denied("casework_form_invalid", 400)
        if length < 0 or length > 262144:
            return denied("casework_form_too_large", 413)
        try:
            if not _budget(request):
                response = denied("casework_rate_limited", 429)
                response["Retry-After"] = "60"
                return response
        except (DatabaseError, SyntheticWriteDenied, MaintenanceUnavailable):
            return denied("casework_store_unavailable", 503)
        return private(self.get_response(request), head=request.method == "HEAD")
