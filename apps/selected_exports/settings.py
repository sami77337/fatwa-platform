"""Isolated synthetic integration profile; all export grants still default deny."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.selected_exports"]))  # noqa: F405
ROOT_URLCONF = "apps.selected_exports.urls"
FATWA_SELECTED_EXPORTS_ENABLED = False
FATWA_SELECTED_EXPORTS_AUTHORITY = None
FATWA_SELECTED_EXPORTS_TTL_SECONDS = 1800
FATWA_SELECTED_EXPORTS_LEASE_SECONDS = 120
DATA_UPLOAD_MAX_NUMBER_FIELDS = 32
