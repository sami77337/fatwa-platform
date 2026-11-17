"""Owned synthetic research composition. Shared integration is coordinator-owned."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.research_workspace"]  # noqa: F405
FATWA_RESEARCH_WORKSPACE_ENABLED = False
FATWA_RESEARCH_WORKSPACE_RIGHTS = None
ROOT_URLCONF = "apps.research_workspace.urls"
