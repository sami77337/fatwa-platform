"""App-local integration settings; shared registration belongs to the coordinator."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.public_answer_media"]))  # noqa: F405
ROOT_URLCONF = "config.campaign_urls"
FATWA_PUBLIC_ANSWER_MEDIA_ENABLED = False
FATWA_PUBLIC_ANSWER_MEDIA_PUBLIC_ENABLED = False
FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY = None
