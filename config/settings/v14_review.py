"""Strict V14 synthetic composition; authorities and features remain opt-in.

This profile preserves V12–V13 source, maintenance and encrypted-recovery
boundaries. It supplies no case, source, media or publication permission.
"""

from .campaign_review import *  # noqa: F403

FATWA_SOURCE_RIGHTS_ENFORCED = True
FATWA_RECOVERY_MAINTENANCE_REQUIRED = True
FATWA_RECOVERY_ENCRYPTION_REQUIRED = True
FATWA_RECOVERY_V10_TEST_COMPAT = False
