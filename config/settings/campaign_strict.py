"""Closed V11/V12 application composition; offline bootstrap is a separate process.

No authority, identity verifier, media store or maintenance root is provisioned by
importing settings. Missing configuration denies application writes and reads.
The dedicated V10 compatibility module must never be used to serve this runtime.
"""

from .campaign_review import *

FATWA_RECOVERY_MAINTENANCE_REQUIRED = True
FATWA_SOURCE_RIGHTS_ENFORCED = True
FATWA_RECOVERY_ENCRYPTION_REQUIRED = True
FATWA_RECOVERY_V10_TEST_COMPAT = False
