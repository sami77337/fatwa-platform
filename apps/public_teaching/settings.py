# ruff: noqa: F403,F405
from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(
    dict.fromkeys([*INSTALLED_APPS, "apps.public_teaching", "apps.precise_citations"])
)  # noqa: F405
ROOT_URLCONF = "config.campaign_urls"
FATWA_PUBLIC_TEACHING_ENABLED = False
FATWA_PUBLIC_TEACHING_PUBLIC_ENABLED = False
FATWA_PUBLIC_TEACHING_AUTHORITY = None
