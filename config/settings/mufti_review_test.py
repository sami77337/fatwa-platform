"""Isolated owned PostgreSQL tests; never imported by public settings."""
from .delivery_queue_test import *

INSTALLED_APPS = [*INSTALLED_APPS, 'apps.mufti_review.apps.MuftiReviewConfig']
