"""Old casework profiles retain answer integrity without optional library schema."""

import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase


class EditorProfileCompatibilityTests(TestCase):
    def test_real_media_service_import_and_strict_editor_identity_in_older_profiles(self):
        code = """
import django
django.setup()
from django.apps import apps
from django.test import override_settings
from apps.casework import services as cases
from apps.answer_media import services
from apps.answer_media.editor_boundary import EditorBoundary
import sys

assert callable(services.manifest_for_locked_answer)
assert not apps.is_installed('apps.research_library')
assert 'apps.research_library.models' not in sys.modules

class Directory:
    provider_id = 'isolated-compatibility-directory'
    epoch = 'current-scope'
    def projection_epoch(self):
        return self.epoch

directory = Directory()
with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory):
    boundary = EditorBoundary(directory)
    boundary.check()
    directory.epoch = 'revoked-scope'
    try:
        boundary.check()
    except cases.CaseConflict:
        pass
    else:
        raise AssertionError('late identity revision did not revoke the response')
    for invalid in (None, '', 1, 'x' * 131073):
        directory.epoch = invalid
        try:
            EditorBoundary(directory)
        except cases.CaseConflict:
            pass
        else:
            raise AssertionError('missing or invalid pure identity revision was accepted')
print('ISOLATED_PROFILE_IDENTITY_PASS')
"""
        root = Path(__file__).resolve().parents[2]
        for profile in ("config.settings.casework_test", "apps.team_updates.test_settings"):
            with self.subTest(profile=profile):
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=root,
                    env={**os.environ, "DJANGO_SETTINGS_MODULE": profile, "FATWA_PRODUCTION": "0"},
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), "ISOLATED_PROFILE_IDENTITY_PASS")
