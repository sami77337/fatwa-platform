"""Opt-in local profile. Trusted server objects must be supplied separately."""

import os

from config.settings.casework_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.case_delivery_desk"]  # noqa: F405
ROOT_URLCONF = "apps.case_delivery_desk.urls"
FATWA_CASEWORK_WEB_ENABLED = os.environ.get("FATWA_CASE_DELIVERY_DESK_ENABLED") == "1"
FATWA_CASE_DELIVERY_APPROVAL_VERIFIER = None
FATWA_CASE_DELIVERY_PROVIDER_VERIFIER = None
