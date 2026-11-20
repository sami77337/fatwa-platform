"""Owned synthetic lane settings; shared campaign integration belongs to root."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.scholarly_links"]))  # noqa: F405
FATWA_SCHOLARLY_LINKS_ENABLED = False
FATWA_SCHOLARLY_LINKS_AUTHORITY = None
ROOT_URLCONF = "apps.scholarly_links.urls"
# The integrated campaign owns both native entry forms and the context processor.
# Reapplying the former standalone template overlays would duplicate those forms.
