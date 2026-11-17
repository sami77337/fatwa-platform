"""Isolated V10 composition. Default closed; never imported by production settings."""

from config.settings.campaign_review import *  # noqa: F403

if "apps.library_preview" not in INSTALLED_APPS:  # noqa: F405
    INSTALLED_APPS = [*INSTALLED_APPS, "apps.library_preview"]  # noqa: F405
FATWA_LIBRARY_PREVIEW_ENABLED = False
FATWA_LIBRARY_PREVIEW_POLICY = None
ROOT_URLCONF = "apps.library_preview.urls"
MIDDLEWARE = [
    "apps.library_preview.guard.PreviewCompositionGuard"
    if item == "apps.casework_web.guard.CaseworkGuard"
    else item
    for item in MIDDLEWARE  # noqa: F405
]  # noqa: F405
