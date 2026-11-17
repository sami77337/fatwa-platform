"""Historical SQLite experiments cannot participate in the maintained PG recovery cut."""

import os

from django.conf import settings


def require_isolated_legacy_store():
    # Pure historical tests may deliberately have no Django configuration. A
    # selected strict module must be checked even before django.setup() runs.
    if settings.configured or os.environ.get("DJANGO_SETTINGS_MODULE"):
        from apps.platform_recovery.integration import MaintenanceUnavailable

        if getattr(settings, "FATWA_RECOVERY_MAINTENANCE_REQUIRED", False) is not False:
            raise MaintenanceUnavailable("legacy_store_unavailable_in_maintained_runtime")
