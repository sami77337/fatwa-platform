"""Pure receipt pins across the final HTTP render; never open a DB transaction."""

from . import services


class UploadSecurityResponses:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.casework_web.guard import denied
        from apps.staff_sessions.integration import retain_final_guard

        try:
            with services.projection() as guard:
                retain_final_guard(
                    guard.check,
                    failure=services.UploadSecurityDenied,
                    code="private_file_unavailable",
                )
                response = self.get_response(request)
                if getattr(response, "streaming", False) and guard.uses:
                    raise services.UploadSecurityDenied("BUFFERED_PROJECTION_REQUIRED")
                return response
        except services.UploadSecurityDenied:
            response = denied("private_file_unavailable", 404)
            # This outer denial may replace a signed private-media response.
            # Do not let its locator become a referrer on a later navigation.
            response["Referrer-Policy"] = "no-referrer"
            return response
