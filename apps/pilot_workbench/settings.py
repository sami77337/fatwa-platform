"""Owned focused test composition; no runtime fixture or implicit activation."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.pilot_workbench"]))  # noqa: F405
ROOT_URLCONF = "apps.pilot_workbench.urls"
FATWA_PILOT_WORKBENCH_ENABLED = False
FATWA_PILOT_WORKBENCH = None
