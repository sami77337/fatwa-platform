"""Owned development composition. Every new capability remains denied by default."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.public_collections"]))  # noqa: F405
FATWA_PUBLIC_COLLECTIONS_ENABLED = False
FATWA_PUBLIC_COLLECTIONS_AUTHORITY = None
ROOT_URLCONF = "config.campaign_urls"
