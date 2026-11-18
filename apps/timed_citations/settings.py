"""Standalone synthetic composition; shared routing/enablement belongs to integration."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.timed_citations"]))  # noqa: F405
FATWA_TIMED_CITATIONS_ENABLED = False
ROOT_URLCONF = "apps.timed_citations.urls"
MIDDLEWARE = [
    "apps.timed_citations.guard.TimedCitationGuard"
    if item == "apps.library_preview.guard.PreviewCompositionGuard"
    else item
    for item in MIDDLEWARE  # noqa: F405
]
