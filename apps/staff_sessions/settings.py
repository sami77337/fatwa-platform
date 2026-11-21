"""Isolated development composition; production identity policy remains unset."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS]  # noqa: F405
if "apps.staff_sessions" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.staff_sessions")
FATWA_STAFF_SESSIONS_ENABLED = False
FATWA_STAFF_SESSION_AUTHORITY = None
FATWA_STAFF_SESSION_RUNTIME_EPOCH = None
