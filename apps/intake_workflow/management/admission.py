"""Strict application administration boundaries; not a PostgreSQL privilege firewall."""

from functools import wraps

from django.core.management.base import BaseCommand, CommandError

from apps.platform_recovery.admission import require_supported_command
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


def install_management_boundary():
    """Cover Django CLI and direct call_command, including command instances.

    Installed once by the synthetic app config; evaluated against current settings
    at every call. Stock execute->handle commands share this boundary. Arbitrary
    Python calling handle/ORM directly remains outside supported administration.
    Explicit overrides also reject stock commands that specialize execute.
    """
    original = BaseCommand.execute
    if getattr(original, "fatwa_maintenance_boundary", False):
        return

    @wraps(original)
    def execute(command, *args, **options):
        if not required():
            return original(command, *args, **options)
        name = type(command).__module__.rsplit(".", 1)[-1]
        try:
            require_supported_command(name)
        except MaintenanceUnavailable:
            raise CommandError("STRICT_ADMINISTRATION_UNSUPPORTED") from None
        try:
            with mutation_scope():
                return original(command, *args, **options)
        except MaintenanceUnavailable:
            raise CommandError("MAINTENANCE_ADMINISTRATION_UNAVAILABLE") from None

    execute.fatwa_maintenance_boundary = True
    BaseCommand.execute = execute
