import json

from django.core.management.base import BaseCommand, CommandError

from apps.casework.services import CaseConflict
from apps.publication_schedules.services import run_due


class Command(BaseCommand):
    help = "Run one bounded due-publication pass with current configured synthetic authorities."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        try:
            result = run_due(limit=options["limit"])
        except CaseConflict as exc:
            raise CommandError("Due publication unavailable under current configuration") from exc
        self.stdout.write(json.dumps(result, sort_keys=True))
