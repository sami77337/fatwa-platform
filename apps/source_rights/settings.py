"""Isolated test composition. Integrator owns the shared flags and dispatcher."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.source_rights"]  # noqa: F405
FATWA_SOURCE_RIGHTS_ENABLED = False
FATWA_SOURCE_RIGHTS_AUTHORITY = None
ROOT_URLCONF = "apps.source_rights.urls"
