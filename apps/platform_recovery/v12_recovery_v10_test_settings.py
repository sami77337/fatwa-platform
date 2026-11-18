"""Isolated V10 compatibility tests ONLY; never use for a V11/V12 application.

Select explicitly as DJANGO_SETTINGS_MODULE inside the disposable PostgreSQL
helper. Ordinary profiles cannot enable plaintext bundles with flags alone.
"""

from config.settings.campaign_review import *  # noqa: F403

FATWA_RECOVERY_ENCRYPTION_REQUIRED = False
FATWA_RECOVERY_V10_TEST_COMPAT = True
