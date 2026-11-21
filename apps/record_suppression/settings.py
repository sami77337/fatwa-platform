"""Owned development profile; root owns shared feature registration."""

# ruff: noqa: F403,F405
from config.settings.campaign_review import *

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.record_suppression"]))
FATWA_RECORD_SUPPRESSION_ENABLED = False
FATWA_RECORD_SUPPRESSION_AUTHORITY = None
FATWA_RECORD_SUPPRESSION_JOURNAL = None
ROOT_URLCONF = "config.campaign_urls"
