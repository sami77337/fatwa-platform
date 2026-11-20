"""Disposable synthetic profile; no public/default registration or grants."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS]  # noqa: F405
if "apps.precise_citations" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.precise_citations")
FATWA_PRECISE_CITATIONS_ENABLED = False
FATWA_PRECISE_CITATIONS_AUTHORITY = None
