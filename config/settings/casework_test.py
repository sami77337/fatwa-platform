"""Owned synthetic PostgreSQL casework tests; never imported by public settings."""

from .mufti_review_test import *

INSTALLED_APPS = [
    *INSTALLED_APPS,
    "apps.casework.apps.CaseworkConfig",
    "apps.casework_web.apps.CaseworkWebConfig",
    # Durable answer parts must remain visible to integrity/delivery checks in
    # every casework profile, even when all multipart UI/release flags are off.
    "apps.answer_media",
]
