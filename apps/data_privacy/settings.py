# ruff: noqa: F403,F405
from config.settings.campaign_review import *

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.data_privacy"]))
FATWA_DATA_PRIVACY_ENABLED = False
FATWA_DATA_PRIVACY_AUTHORITY = None
