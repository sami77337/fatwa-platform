"""Explicit synthetic CLI; no HTTP mutation or outer transaction."""
from dataclasses import asdict
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from apps.intake_workflow import contracts as c, guards
from apps.intake_workflow.review import transition_review


class Command(BaseCommand):
    help = 'Append a synthetic internal review event and transition its item atomically; never approve or publish.'

    def add_arguments(self, parser):
        parser.add_argument('--item', required=True)
        parser.add_argument('--operation', required=True)
        parser.add_argument('--action', required=True, choices=list(c.ReviewAction))
        parser.add_argument('--expected-status', required=True, choices=list(c.ReviewStatus))
        parser.add_argument('--reason', required=True)
        parser.add_argument('--synthetic-fixtures-only', action='store_true', default=False)

    def handle(self, *args, **options):
        try:
            result = transition_review(options['item'], operation_id=options['operation'], action=options['action'],
                expected_status=options['expected_status'], reason=options['reason'],
                synthetic_fixtures_only=options['synthetic_fixtures_only'])
        except (c.ContractError, guards.SyntheticWriteDenied) as exc:
            raise CommandError(exc.code) from None
        except DatabaseError:
            raise CommandError('REVIEW_DATABASE_UNAVAILABLE') from None
        self.stdout.write(json.dumps(asdict(result), default=str, sort_keys=True))
