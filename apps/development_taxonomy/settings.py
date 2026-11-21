"""Disposable synthetic profile, independent of any accepted taxonomy corpus."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS]  # noqa: F405
if "apps.development_taxonomy" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.development_taxonomy")
FATWA_DEVELOPMENT_TAXONOMY_ENABLED = False
FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY = None
