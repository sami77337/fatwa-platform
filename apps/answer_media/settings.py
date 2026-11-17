"""Only the isolated test composition; all grants are fixture configured."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(INSTALLED_APPS)  # noqa: F405
if "apps.answer_media" not in INSTALLED_APPS:
    INSTALLED_APPS.append("apps.answer_media")
ROOT_URLCONF = "apps.answer_media.urls"
FATWA_ANSWER_MEDIA_ENABLED = False
FATWA_ANSWER_MEDIA_PRIVATE_ENABLED = False
