"""Standalone loopback route guard; coordinator must explicitly compose this route."""

import re

from django.core.exceptions import DisallowedHost
from django.db import DatabaseError

from apps.casework_web import guard as staff_guard
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.library_preview.guard import PreviewCompositionGuard

from . import services

PDF_ROUTE = re.compile(
    r"/casework/staff/pdf-citations/[0-9a-f-]{36}/"
    r"(?:document|review-document|page|review-page)/"
)


def boundary(request):
    try:
        services._enabled()
        if not staff_guard.enabled():
            return staff_guard.denied("pdf_unavailable", 404)
        if request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"} or any(
            key in request.META
            for key in ("HTTP_FORWARDED", "HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_HOST")
        ):
            return staff_guard.denied("pdf_unavailable", 403)
        if re.fullmatch(r"(?:127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", request.get_host()) is None:
            return staff_guard.denied("pdf_unavailable", 400)
        if request.method not in {"GET", "HEAD"} or request.GET:
            return staff_guard.denied("pdf_unavailable", 405)
    except (DisallowedHost, services.cases.CaseConflict):
        return staff_guard.denied("pdf_unavailable", 404)
    return None


class PdfCitationGuard:
    """Owned test composition; no route exemption is added to shared middleware."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.existing = PreviewCompositionGuard(get_response)

    def __call__(self, request):
        if not PDF_ROUTE.fullmatch(request.path):
            return self.existing(request)
        refused = boundary(request)
        if refused:
            return refused
        try:
            if not staff_guard._budget(request):
                return staff_guard.denied("pdf_rate_limited", 429)
        except (DatabaseError, SyntheticWriteDenied):
            return staff_guard.denied("pdf_unavailable", 503)
        return staff_guard.private(self.get_response(request))
