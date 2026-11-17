"""Isolated test composition; every publication grant remains explicitly configured."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(INSTALLED_APPS)  # noqa: F405
if "apps.experimental_publication" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.experimental_publication")
FATWA_EXPERIMENTAL_PUBLICATION_ENABLED = False
FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY = None
