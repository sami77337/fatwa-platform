"""Recorder opt-in must not broaden the CSP of private original byte responses."""

from django.http import HttpResponse
from django.test import SimpleTestCase, override_settings

from apps.casework_web.guard import private
from tests.casework.test_http import WEB_SETTINGS


@override_settings(**WEB_SETTINGS, FATWA_BROWSER_AUDIO_ENABLED=True)
class RecorderCSPExternalReview(SimpleTestCase):
    def test_recorder_policy_preserves_byte_sandbox_and_disallows_inline_and_remote_code(self):
        marker = '<fieldset data-browser-audio data-input-name="attachment">'
        regular = private(HttpResponse("Synthetic page"))
        self.assertNotIn("microphone=(self)", regular.get("Permissions-Policy", ""))
        page = private(HttpResponse(marker))
        self.assertEqual(page["Permissions-Policy"], "microphone=(self), camera=()")
        policy = page["Content-Security-Policy"]
        for fragment in (
            "default-src 'none'",
            "script-src 'self'",
            "worker-src 'self'",
            "media-src 'self' blob:",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ):
            self.assertIn(fragment, policy)
        for fragment in ("'unsafe-inline'", "'unsafe-eval'", "https:", "script-src *"):
            self.assertNotIn(fragment, policy)
        for content_type in ("text/html", "text/plain", "audio/wav"):
            response = HttpResponse(marker, content_type=content_type)
            response["Content-Security-Policy"] = "sandbox; default-src 'none'"
            sealed = private(response)
            self.assertEqual(sealed["Content-Security-Policy"], "sandbox; default-src 'none'")
            self.assertNotIn("microphone=(self)", sealed.get("Permissions-Policy", ""))
