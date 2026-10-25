"""Local synthetic preview using the application's existing development guards."""

import os

import django
from django.core.management.commands.runserver import Command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()


class FollowupPreview(Command):
    def check_migrations(self):
        self.stdout.write("Synthetic follow-up preview: no database preflight or changes.")


if __name__ == "__main__":
    FollowupPreview().run_from_argv(
        ["editorial-followup", "runserver", "127.0.0.1:8016", "--noreload"]
    )
