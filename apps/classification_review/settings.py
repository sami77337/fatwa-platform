"""Isolated synthetic wiring. All permissions/features default closed."""

from apps.knowledge_links.settings import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.classification_review"]))  # noqa: F405
FATWA_CLASSIFICATION_REVIEW_ENABLED = False
FATWA_CLASSIFICATION_REVIEW_AUTHORITY = None
ROOT_URLCONF = "apps.classification_review.urls"
