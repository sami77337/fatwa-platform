"""Installation preference never supplies authentication or case authority."""

from django.conf import settings


def installable_staff(request):
    sessions_url = ""
    privacy_url = ""
    permissions_url = ""
    mfa_url = ""
    lifecycle_url = ""
    if getattr(settings, "FATWA_RECORD_SUPPRESSION_ENABLED", False) is True:
        if request.path.startswith("/casework/operations/"):
            lifecycle_url = "/casework/operations/record-lifecycle/"
        elif request.path.startswith("/casework/staff/"):
            lifecycle_url = "/casework/staff/record-lifecycle/"
    if getattr(settings, "FATWA_STAFF_MFA_ENABLED", False) is True:
        if request.path.startswith("/casework/operations/"):
            mfa_url = "/casework/operations/mfa/"
        elif request.path.startswith("/casework/staff/"):
            mfa_url = "/casework/staff/mfa/"
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
        "media_derivatives_url": "/casework/staff/media-jobs/"
        if request.path.startswith("/casework/staff/")
        and getattr(settings, "FATWA_MEDIA_DERIVATIVES_ENABLED", False) is True
        else "",
        "record_lifecycle_url": lifecycle_url,
        "staff_mfa_url": mfa_url,
        "permissions_management_url": permissions_url,
        "privacy_management_url": privacy_url,
        "staff_sessions_url": sessions_url,
        "staff_pwa_enabled": request.path.startswith("/casework/staff/")
        and getattr(settings, "FATWA_STAFF_PWA_ENABLED", False) is True,
    }
