"""Focused test composition. The shared campaign is wired separately by integration."""

from copy import deepcopy

from config.settings.campaign_review import *  # noqa: F403

if not any(app.startswith("apps.mufti_workspace") for app in INSTALLED_APPS):  # noqa: F405
    INSTALLED_APPS = [*INSTALLED_APPS, "apps.mufti_workspace"]  # noqa: F405
TEMPLATES = deepcopy(TEMPLATES)  # noqa: F405
processor = "apps.mufti_workspace.context.case_workspace"
if processor not in TEMPLATES[0]["OPTIONS"]["context_processors"]:
    TEMPLATES[0]["OPTIONS"]["context_processors"].append(processor)
FATWA_MUFTI_WORKSPACE_ENABLED = False
