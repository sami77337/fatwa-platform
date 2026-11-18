"""Hold maintenance admission through migration checks, commits and signals."""

from django.core.management.commands.migrate import Command as DjangoMigrate

from apps.intake_workflow.management.admission import AdmittedCommand


class Command(AdmittedCommand, DjangoMigrate):
    pass
