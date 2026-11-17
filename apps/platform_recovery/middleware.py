"""Topmost synchronous gate, including GET throttle/session writes and on_commit."""

from django.http import JsonResponse

from .integration import MaintenanceUnavailable, mutation_scope


def unavailable():
    response = JsonResponse({"error": "maintenance_unavailable"}, status=503)
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["X-Content-Type-Options"] = "nosniff"
    response["Retry-After"] = "60"
    return response


class MaintenanceGuard:
    sync_capable = True
    async_capable = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            with mutation_scope():
                response = self.get_response(request)
                # No synchronous admission lease can be lent to a later iterator.
                if response.streaming:
                    response.close()
                    return unavailable()
                return response
        except MaintenanceUnavailable:
            return unavailable()
