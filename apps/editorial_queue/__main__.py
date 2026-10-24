"""Loopback preview with no database preflight, using the existing Django guards."""

import os

import django
from django.core.management.commands.runserver import Command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()


class QueuePreview(Command):
    def check_migrations(self):
        self.stdout.write("Synthetic queue preview: no database preflight or changes.")


QueuePreview().run_from_argv(["editorial-queue", "runserver", "127.0.0.1:8014", "--noreload"])
