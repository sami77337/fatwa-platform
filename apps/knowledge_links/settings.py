"""Isolated composition for this lane; integrator owns shared settings/dispatcher."""

from config.settings.campaign_review import *  # noqa: F403

if "apps.knowledge_links" not in INSTALLED_APPS:  # noqa: F405
    INSTALLED_APPS = [*INSTALLED_APPS, "apps.knowledge_links"]  # noqa: F405
FATWA_KNOWLEDGE_LINKS_ENABLED = False
FATWA_KNOWLEDGE_LINKS_AUTHORITY = None
ROOT_URLCONF = "apps.knowledge_links.urls"
