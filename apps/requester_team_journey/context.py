"""Navigation visibility only; every destination enforces its own independent gate."""

from django.apps import apps
from django.conf import settings


def connected_navigation(request):
    return {
        "library_preview_navigation": apps.is_installed("apps.library_preview")
        and getattr(settings, "FATWA_LIBRARY_PREVIEW_ENABLED", False) is True,
        "source_desk_navigation": request.path == "/casework/staff/"
        and getattr(settings, "FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED", False) is True,
    }
