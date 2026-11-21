# ruff: noqa: F403,F405
from config.settings.campaign_review import *

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.permission_sets"]))
FATWA_PERMISSION_SETS_ENABLED = False
FATWA_PERMISSION_SETS_MANAGEMENT_AUTHORITY = None
