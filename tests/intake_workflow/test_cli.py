"""Actual pure/management check processes with an unreachable DB and writes off."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from apps.intake_workflow import fixtures as f

ROOT=Path(__file__).resolve().parents[2]


class CliTests(unittest.TestCase):
    def command(self, *args):
        env={k:v for k,v in os.environ.items() if not re.search(
            r'^(PG|DJANGO_|FATWA_|DATABASE_URL$|PYTHONPATH$|PYTHONHOME$)|PASSWORD|SECRET|TOKEN|API_KEY',k,re.I)}
        env.update(FATWA_PRODUCTION='0',FATWA_WAVE7_SYNTHETIC_WRITES='0',PGHOST='127.0.0.1',
                   PGPORT='1',PGDATABASE='wave7_synthetic_cli_unreachable',
                   PGTESTDATABASE='test_wave7_synthetic_cli_unreachable')
        return subprocess.run([sys.executable,*args],cwd=ROOT,env=env,capture_output=True,timeout=40)

    def test_pure_check_actual_process_without_django_setup_or_database(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic.json'
            source.write_bytes(f.synthetic_payload())
            result=self.command('-m','tools.content_intake','wave7-check',str(source),'--synthetic-fixtures-only')
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(json.loads(result.stdout)['item_count'],8)
        self.assertNotIn(f.ORIGINAL_QUESTION.encode(),result.stdout)

    def test_management_check_actual_process_with_disabled_writes_and_port_one(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic.json'
            source.write_bytes(f.synthetic_payload())
            result=self.command('manage.py','wave7_intake','check',str(source),'--synthetic-fixtures-only',
                                '--settings=config.settings.wave7_test')
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(json.loads(result.stdout)['item_count'],8)

    def test_check_and_import_refuse_without_literal_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic.json';source.write_bytes(f.synthetic_payload())
            for action in ('check','import'):
                result=self.command('manage.py','wave7_intake',action,str(source),
                                    '--idempotency-key','key','--settings=config.settings.wave7_test')
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn('Traceback',result.stderr.decode())

    def test_import_refusal_and_file_errors_are_sanitized_no_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic.json';source.write_bytes(f.synthetic_payload())
            result=self.command('manage.py','wave7_intake','import',str(source),'--synthetic-fixtures-only',
                                '--idempotency-key','key','--settings=config.settings.wave7_test')
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(json.loads(result.stdout)['code'],'WRITES_DISABLED')
            result=self.command('manage.py','wave7_intake','check',str(source.with_name('absent-private-name')),
                                '--synthetic-fixtures-only','--settings=config.settings.wave7_test')
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('absent-private-name',result.stdout.decode()+result.stderr.decode())
            self.assertNotIn('Traceback',result.stderr.decode())

    def test_oversized_file_rejects_without_output_directory_or_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic.json';source.write_bytes(b' '*1_000_001)
            result=self.command('-m','tools.content_intake','wave7-check',str(source),'--synthetic-fixtures-only')
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(json.loads(result.stdout)['status'],'ERROR')
            self.assertEqual(list(Path(directory).iterdir()),[source])

    def test_public_settings_service_refuses_via_guard_before_model_import(self):
        code='''
import os
os.environ['DJANGO_SETTINGS_MODULE']='config.settings.test'
os.environ['FATWA_WAVE7_SYNTHETIC_WRITES']='1'
import django
django.setup()
from apps.intake_workflow.intake import import_intake
from apps.intake_workflow.fixtures import synthetic_payload
from apps.intake_workflow.guards import SyntheticWriteDenied
try:
    import_intake(synthetic_payload(),idempotency_key='key',synthetic_fixtures_only=True)
except SyntheticWriteDenied as exc:
    assert exc.code=='UNTRUSTED_SCOPE_OR_SOURCE_CONFIG',exc.code
    print(exc.code)
else:
    raise AssertionError('public settings allowed a workflow write')
'''
        result=self.command('-c',code)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(result.stdout.strip(),b'UNTRUSTED_SCOPE_OR_SOURCE_CONFIG')
