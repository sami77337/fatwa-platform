from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(INSTALLED_APPS)  # noqa: F405
if "apps.data_quality" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.data_quality")
FATWA_DATA_QUALITY_ENABLED = False
ROOT_URLCONF = "apps.data_quality.urls"
