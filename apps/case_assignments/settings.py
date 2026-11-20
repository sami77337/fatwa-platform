"""Closed synthetic integration profile; tests explicitly enable coordination."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(INSTALLED_APPS)  # noqa: F405
if "apps.case_assignments" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.case_assignments")
FATWA_CASE_ASSIGNMENTS_ENABLED = False
FATWA_CASE_ASSIGNMENT_CANDIDATES = None
