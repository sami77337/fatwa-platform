"""Owned synthetic research composition. Shared integration is coordinator-owned."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.research_workspace"]))  # noqa: F405
FATWA_RESEARCH_WORKSPACE_ENABLED = False
FATWA_RESEARCH_WORKSPACE_RIGHTS = None
FATWA_RESEARCH_COLLECTIONS_ENABLED = False
ROOT_URLCONF = "apps.research_workspace.urls"
