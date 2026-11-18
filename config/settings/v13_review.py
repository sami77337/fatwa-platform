"""Strict V13 synthetic composition; no feature or authority is enabled here.

An explicitly initialized maintenance/private-storage root and current source
authority are required before application work. Older isolated test profiles
retain their own contracts; this profile cannot opt into plaintext V10 recovery.
"""

from .campaign_review import *  # noqa: F403

FATWA_SOURCE_RIGHTS_ENFORCED = True
FATWA_RECOVERY_MAINTENANCE_REQUIRED = True
FATWA_RECOVERY_ENCRYPTION_REQUIRED = True
FATWA_RECOVERY_V10_TEST_COMPAT = False
