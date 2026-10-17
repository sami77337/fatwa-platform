"""No-database checks for the shared, opt-in E2 URL registration."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


class ReviewWiringTests(unittest.TestCase):
    def probe(self, profile, value=None, *, legacy_review=False):
        environment = dict(os.environ, DJANGO_SETTINGS_MODULE=profile, PGPORT='1')
        environment.pop('FATWA_WAVE7_REVIEW_READ', None)
        environment.pop('FATWA_WAVE7_SYNTHETIC_READS', None)
        if value is not None:
            environment['FATWA_WAVE7_SYNTHETIC_READS'] = value
        if legacy_review:
            environment['FATWA_WAVE7_REVIEW_READ'] = '1'
        result = subprocess.run([sys.executable, '-c', '''
import json, django
django.setup()
from django.conf import settings
from django.urls import resolve, Resolver404
match = resolve('/dev/editorial-preview/persisted')
routes=[]
for path in ('/dev/wave7/api/batches','/dev/wave7/api/items','/dev/wave7/api/items/not-a-uuid'):
    try: routes.append(resolve(path).url_name)
    except Resolver404: routes.append(None)
print(json.dumps(dict(enabled=getattr(settings, 'WAVE7_REVIEW_READ_ENABLED', None),
    reads_enabled=getattr(settings, 'WAVE7_READS_ENABLED', None), api_routes=routes,
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
        self.assertIsNone(result['reads_enabled'])
        self.assertEqual(result['api_routes'], [None] * 3)

    def test_wave7_profile_requires_literal_opt_in(self):
        for value in (None, '', 'true', '0'):
            with self.subTest(value=value):
                result = self.probe('config.settings.wave7_test', value)
                self.assertIs(result['enabled'], False)
                self.assertIs(result['reads_enabled'], False)

    def test_wave7_static_route_precedes_legacy_generic_identifier(self):
        result = self.probe('config.settings.wave7_test', '1')
        self.assertEqual(result, dict(enabled=True, reads_enabled=True,
            api_routes=['wave7_api_batches', 'wave7_api_items', 'wave7_api_item'], view='persisted_review',
            name='wave7_editorial_review', installed=True))

    def test_obsolete_review_flag_alone_cannot_enable_either_reader(self):
        result = self.probe('config.settings.wave7_test', legacy_review=True)
        self.assertIs(result['enabled'], False)
        self.assertIs(result['reads_enabled'], False)
