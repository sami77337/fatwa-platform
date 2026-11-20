"""Installation preference never supplies authentication or case authority."""

from django.conf import settings


def installable_staff(request):
    return {
        "staff_pwa_enabled": request.path.startswith("/casework/staff/")
        and getattr(settings, "FATWA_STAFF_PWA_ENABLED", False) is True,
    }
