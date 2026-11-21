"""Installation preference never supplies authentication or case authority."""

from django.conf import settings


def installable_staff(request):
    sessions_url = ""
    privacy_url = ""
    permissions_url = ""
    if getattr(settings, "FATWA_PERMISSION_SETS_ENABLED", False) is True:
        if request.path.startswith("/casework/operations/"):
            permissions_url = "/casework/operations/permissions/"
        elif request.path.startswith("/casework/staff/"):
            permissions_url = "/casework/staff/permissions/"
    if getattr(settings, "FATWA_DATA_PRIVACY_ENABLED", False) is True:
        if request.path.startswith("/casework/operations/"):
            privacy_url = "/casework/operations/privacy/"
        elif request.path.startswith("/casework/staff/"):
            privacy_url = "/casework/staff/privacy/"
    if getattr(settings, "FATWA_STAFF_SESSIONS_ENABLED", False) is True:
        if request.path.startswith("/casework/operations/"):
            sessions_url = "/casework/operations/sessions/"
        elif request.path.startswith("/casework/staff/"):
            sessions_url = "/casework/sessions/"
    return {
        "permissions_management_url": permissions_url,
        "privacy_management_url": privacy_url,
        "staff_sessions_url": sessions_url,
        "staff_pwa_enabled": request.path.startswith("/casework/staff/")
        and getattr(settings, "FATWA_STAFF_PWA_ENABLED", False) is True,
    }
