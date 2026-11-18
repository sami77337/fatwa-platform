"""Unsupported general-purpose administration fails closed in strict mode."""

from django.core.management.commands.shell import Command as DjangoCommand

from apps.intake_workflow.management.admission import UnsupportedStrictCommand


class Command(UnsupportedStrictCommand, DjangoCommand):
    pass
