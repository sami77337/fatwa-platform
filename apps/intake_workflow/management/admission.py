"""Strict application administration boundaries; not a PostgreSQL privilege firewall."""

from django.core.management.base import CommandError

from apps.platform_recovery.integration import (
    MaintenanceUnavailable,
    mutation_scope,
    required,
)


class UnsupportedStrictCommand:
    """Reject before Django checks, file opening, SQL, prompts or command output.

    Generic shells, fixture resets and unscoped exports cannot prove that their
    writes participate in admission or that their output is an encrypted bundle.
    The explicit older profile retains Django's original command behavior.
    """

    def execute(self, *args, **options):
        if required():
            raise CommandError("STRICT_ADMINISTRATION_UNSUPPORTED")
        return super().execute(*args, **options)


class AdmittedCommand:
    """Keep admission through native commits, callbacks and output finalization."""

    def execute(self, *args, **options):
        try:
            with mutation_scope():
                return super().execute(*args, **options)
        except MaintenanceUnavailable:
            raise CommandError("MAINTENANCE_ADMINISTRATION_UNAVAILABLE") from None
