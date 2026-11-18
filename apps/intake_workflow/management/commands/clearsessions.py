"""Session cleanup needs a reviewed admission-aware implementation in strict mode."""

from django.contrib.sessions.management.commands.clearsessions import Command as DjangoCommand

from apps.intake_workflow.management.admission import UnsupportedStrictCommand


class Command(UnsupportedStrictCommand, DjangoCommand):
    pass
