"""Hold maintenance admission through every migration commit and signal."""

from django.core.management.commands.migrate import Command as DjangoMigrate

from apps.platform_recovery.integration import mutation_service


class Command(DjangoMigrate):
    @mutation_service
    def handle(self, *args, **options):
        return super().handle(*args, **options)
