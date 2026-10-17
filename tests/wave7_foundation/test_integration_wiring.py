"""No-database checks for the shared, opt-in E2 URL registration."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


class ReviewWiringTests(unittest.TestCase):
    def probe(self, profile, value=None):
        environment = dict(os.environ, DJANGO_SETTINGS_MODULE=profile, PGPORT='1')
        environment.pop('FATWA_WAVE7_REVIEW_READ', None)
        if value is not None:
            environment['FATWA_WAVE7_REVIEW_READ'] = value
        result = subprocess.run([sys.executable, '-c', '''
import json, django
django.setup()
from django.conf import settings
from django.urls import resolve
match = resolve('/dev/editorial-preview/persisted')
print(json.dumps(dict(enabled=getattr(settings, 'WAVE7_REVIEW_READ_ENABLED', None),
    view=match.func.__name__, name=match.url_name,
    installed='apps.intake_workflow.apps.IntakeWorkflowConfig' in settings.INSTALLED_APPS)))
'''], cwd=Path(__file__).resolve().parents[2], env=environment,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_public_profile_does_not_register_persisted_service(self):
        result = self.probe('config.settings.test', '1')
        self.assertFalse(result['installed'])
        self.assertNotEqual(result['view'], 'persisted_review')
        self.assertIsNone(result['enabled'])

    def test_wave7_profile_requires_literal_opt_in(self):
        for value in (None, '', 'true', '0'):
            with self.subTest(value=value):
                self.assertIs(self.probe('config.settings.wave7_test', value)['enabled'], False)

    def test_wave7_static_route_precedes_legacy_generic_identifier(self):
        result = self.probe('config.settings.wave7_test', '1')
        self.assertEqual(result, dict(enabled=True, view='persisted_review',
            name='wave7_editorial_review', installed=True))
