"""Owned development profile. Shared registration belongs to the integrator."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.case_lifecycle"]))  # noqa: F405
FATWA_CASE_LIFECYCLE_ENABLED = False
FATWA_CASE_LIFECYCLE_AUTHORITY = None
ROOT_URLCONF = "apps.case_lifecycle.urls"
