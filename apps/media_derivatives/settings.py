"""Isolated disabled development composition; no processor or policy selected."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.media_derivatives"]))  # noqa: F405
FATWA_MEDIA_DERIVATIVES_ENABLED = False
FATWA_MEDIA_DERIVATIVES_AUTHORITY = None
FATWA_MEDIA_DERIVATIVES_PROCESSOR = None
FATWA_MEDIA_DERIVATIVES_WORKER_DIRECTORY = None
ROOT_URLCONF = "config.campaign_urls"
