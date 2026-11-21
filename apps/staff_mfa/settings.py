"""Optional development profile; every identity, key and policy remains unset."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = list(dict.fromkeys([*INSTALLED_APPS, "apps.staff_mfa"]))  # noqa: F405
FATWA_STAFF_MFA_ENABLED = False
FATWA_STAFF_MFA_AUTHORITY = None
FATWA_STAFF_MFA_KEY = None
