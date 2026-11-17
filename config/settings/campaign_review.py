"""Opt-in synthetic requester/team journey; all casework gates remain closed."""

from .casework_review import *  # noqa: F403

INSTALLED_APPS = [
    *INSTALLED_APPS,  # noqa: F405
    "apps.requester_access_review.apps.RequesterAccessReviewConfig",
]
ROOT_URLCONF = "config.campaign_urls"
