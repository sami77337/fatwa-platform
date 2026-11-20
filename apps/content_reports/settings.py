"""Isolated test profile; the feature still requires an explicit runtime opt-in."""

from apps.requester_portal.settings import *  # noqa: F403

INSTALLED_APPS = list(INSTALLED_APPS)  # noqa: F405
if "apps.content_reports" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.content_reports")
ROOT_URLCONF = "apps.content_reports.urls"
FATWA_CONTENT_REPORTS_ENABLED = False
FATWA_CONTENT_REPORTS_AUTHORITY = None
