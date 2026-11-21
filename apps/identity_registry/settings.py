"""Disposable synthetic verification profile; no default grants."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS]  # noqa: F405
if "apps.identity_registry" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.identity_registry")
FATWA_IDENTITY_REGISTRY_ENABLED = False
FATWA_IDENTITY_REGISTRY_AUTHORITY = None
