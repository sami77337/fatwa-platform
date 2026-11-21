# ruff: noqa: F403,F405
from config.settings.campaign_review import *

INSTALLED_APPS = list(
    dict.fromkeys([*INSTALLED_APPS, "apps.publication_destinations", "apps.precise_citations"])
)
ROOT_URLCONF = "apps.publication_destinations.urls"
FATWA_PUBLICATION_DESTINATIONS_ENABLED = False
FATWA_PUBLICATION_DESTINATIONS_AUTHORITY = None
FATWA_PUBLICATION_DESTINATION_PROFILES = None
FATWA_PUBLICATION_DESTINATIONS_PROVIDER_VERIFIER = None
