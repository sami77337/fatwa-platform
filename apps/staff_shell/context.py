"""Installation preference never supplies authentication or case authority."""

from django.conf import settings


def installable_staff(request):
    sessions_url = ""
    if getattr(settings, "FATWA_STAFF_SESSIONS_ENABLED", False) is True:
        if request.path.startswith("/casework/operations/"):
            sessions_url = "/casework/operations/sessions/"
        elif request.path.startswith("/casework/staff/"):
            sessions_url = "/casework/sessions/"
    return {
        "staff_sessions_url": sessions_url,
        "staff_pwa_enabled": request.path.startswith("/casework/staff/")
        and getattr(settings, "FATWA_STAFF_PWA_ENABLED", False) is True,
    }
