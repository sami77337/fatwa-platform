"""Reject writes before view dispatch, and apply headers to every response."""
from collections.abc import Callable

from django.core.exceptions import DisallowedHost
from django.http import HttpRequest, HttpResponse, JsonResponse


class PublicReadOnlyMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Force Django's host validation even on health checks and rejected methods.
        try:
            request.get_host()
            valid_host = True
        except DisallowedHost:
            valid_host = False
        if not valid_host:
            response = JsonResponse({"error": "invalid_host"}, status=400)
        elif request.method not in {"GET", "HEAD"}:
            response = JsonResponse({"error": "method_not_allowed"}, status=405)
            response["Allow"] = "GET, HEAD"
        elif len(request.path_info) > 2048:
            response = JsonResponse({"error": "uri_too_long"}, status=414)
        elif len(request.META.get("QUERY_STRING", "")) > 4096:
            response = JsonResponse({"error": "invalid_query"}, status=400)
        else:
            response = self.get_response(request)
        response["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; base-uri 'none'; "
            "form-action 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response["Referrer-Policy"] = "no-referrer"
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        return response
