import os

from django.conf import settings

from .services import enabled


def organization(request):
    return {
        "organization_enabled": enabled(),
        "reports_enabled": os.environ.get("FATWA_PRODUCTION") == "0"
        and getattr(settings, "FATWA_CONTENT_REPORTS_ENABLED", False) is True,
    }
