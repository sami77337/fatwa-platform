"""Explicit synthetic check/import; no HTTP writes or implicit DB initialization."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from apps.intake_workflow.contracts import ContractError, MAX_INPUT_BYTES
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.intake_workflow.intake import check_intake, import_intake


class Command(BaseCommand):
    help = 'Check or import an explicitly acknowledged synthetic Wave7 JSON batch.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('action', choices=('check','import'))
        parser.add_argument('input',type=Path,nargs='?',help='Compatibility positional input')
        parser.add_argument('--input',dest='input_option',type=Path,help='Synthetic input file')
        parser.add_argument('--synthetic-fixtures-only',action='store_true')
        parser.add_argument('--idempotency-key')

    def handle(self, *args, **options):
        try:
            if options['synthetic_fixtures_only'] is not True:
                raise ContractError('synthetic_acknowledgement_required')
            paths = [options['input'], options['input_option']]
            if sum(path is not None for path in paths) != 1:
                raise ContractError('input: exactly_one_path_required')
            source = next(path for path in paths if path is not None)
            try:
                with source.open('rb') as stream:
                    raw = stream.read(MAX_INPUT_BYTES+1)
            except OSError:
                self.fail('SOURCE_READ_FAILED',400)
            if options['action']=='check':
                result = check_intake(raw,synthetic_fixtures_only=True)
            else:
                result = import_intake(raw,idempotency_key=options['idempotency_key'],
                                       synthetic_fixtures_only=True)
        except ContractError as exc:
            self.fail(exc.code,exc.status_code)
        except SyntheticWriteDenied as exc:
            self.fail(exc.code,403)
        except CommandError:
            raise
        except Exception:
            self.fail('INTAKE_FAILED',500)
        self.stdout.write(json.dumps(result.report(),ensure_ascii=False,sort_keys=True,allow_nan=False))

    def fail(self, code, status):
        self.stdout.write(json.dumps(dict(status='ERROR',code=code,status_code=status),sort_keys=True))
        raise CommandError(code)
