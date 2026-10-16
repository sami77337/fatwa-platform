"""Local Django development server without the unrelated DB migration preflight."""

import os

import django
from django.core.management.commands.runserver import Command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()


class PreviewServer(Command):
    def check_migrations(self):
        self.stdout.write("Synthetic preview: migration preflight skipped; no database changes.")


PreviewServer().run_from_argv(["editorial-demo", "runserver", "127.0.0.1:8012", "--noreload"])
