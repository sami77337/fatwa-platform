"""Opt-in synthetic requester/team journey; all casework gates remain closed."""

from copy import deepcopy
from pathlib import Path

from .casework_review import *  # noqa: F403

INSTALLED_APPS = [
    *INSTALLED_APPS,  # noqa: F405
    "apps.requester_access_review.apps.RequesterAccessReviewConfig",
    "apps.team_updates.apps.TeamUpdatesConfig",
    "apps.case_delivery_desk",
]
FATWA_CASE_DELIVERY_APPROVAL_VERIFIER = None
FATWA_CASE_DELIVERY_PROVIDER_VERIFIER = None
ROOT_URLCONF = "config.campaign_urls"

# One shared composition; optional profile aliases reuse these same overlays.
TEMPLATES = deepcopy(TEMPLATES)  # noqa: F405
TEMPLATES[0]["DIRS"] = [
    Path(__file__).resolve().parents[2] / "apps/requester_team_journey/templates",
    *TEMPLATES[0]["DIRS"],
]
