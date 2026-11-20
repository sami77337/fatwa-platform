"""App-local runner overlay; campaign defaults remain disabled until configured."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS]  # noqa: F405
for _app in ("django.contrib.postgres", "apps.canonical_search"):
    if _app not in INSTALLED_APPS:
        INSTALLED_APPS.append(_app)
FATWA_CANONICAL_SEARCH_ENABLED = False
FATWA_CANONICAL_SEARCH_AUTHORITY = None
