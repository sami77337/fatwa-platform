"""Isolated local profile; coordinator owns registration in the campaign."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(INSTALLED_APPS)  # noqa: F405
if not any(app.startswith("apps.requester_portal") for app in INSTALLED_APPS):
    INSTALLED_APPS.append("apps.requester_portal")
ROOT_URLCONF = "apps.requester_portal.urls"
FATWA_REQUESTER_PORTAL_ENABLED = True
# Media, private release, delivery, identity and source flags retain base defaults.
