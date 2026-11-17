"""Optional local synthetic profile; no production URL or identity changes."""
from apps.casework_web.requester_workspace_settings import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.requester_access_review.apps.RequesterAccessReviewConfig"]  # noqa: F405
ROOT_URLCONF = "apps.requester_access_review.urls"
