"""Fail-closed opt-in and adversarial uploads through the unchanged requester endpoint."""

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import (
    Client,
    RequestFactory,
    SimpleTestCase,
    TransactionTestCase,
    override_settings,
)

from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import Case
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from .assets import asset
from .context import capture


class OptInTests(SimpleTestCase):
    @override_settings(FATWA_CASEWORK_WEB_ENABLED=True, FATWA_BROWSER_AUDIO_ENABLED=False)
    def test_disabled_has_no_widget_or_assets(self):
        request = RequestFactory().get("/casework/audio-capture.js")
        self.assertFalse(capture(request)["audio_capture_enabled"])
        self.assertEqual(asset(request, "capture.js").status_code, 404)

    @override_settings(FATWA_CASEWORK_WEB_ENABLED=True, FATWA_BROWSER_AUDIO_ENABLED=True)
    def test_production_closed_and_assets_fixed(self):
        request = RequestFactory().get("/casework/audio-capture.js")
        with patch.dict("os.environ", FATWA_PRODUCTION="1"):
            self.assertFalse(capture(request)["audio_capture_enabled"])
            self.assertEqual(asset(request, "capture.js").status_code, 404)
        with patch.dict("os.environ", FATWA_PRODUCTION="0"):
            self.assertEqual(asset(request, "../../secret").status_code, 404)
            self.assertEqual(asset(RequestFactory().post("/"), "capture.js").status_code, 404)
            self.assertEqual(asset(RequestFactory().get("/?key=x"), "capture.js").status_code, 404)
            result = asset(request, "capture.js")
            self.assertEqual(result.status_code, 200)
            self.assertIn("no-store", result["Cache-Control"])
            self.assertEqual(result["X-Content-Type-Options"], "nosniff")


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_REQUESTER_PORTAL_ENABLED": True,
        "FATWA_CASE_ATTACHMENTS_ENABLED": True,
    }
)
class UploadBoundaryTests(TransactionTestCase):
    def setUp(self):
        self.receipt = cases.intake_case(
            original_question="اصطناعي",
            source_event_id="audio-boundary",
            requester_id="audio-boundary",
            idempotency_key="audio-boundary",
            synthetic_fixtures_only=True,
        )
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        page = self.client.get("/casework/status/")
        response = post(
            self.client,
            "/casework/status/",
            {"action": "unlock", "token": self.receipt["token"]},
            page,
        )
        self.assertEqual(response.status_code, 303)
        self.page = self.client.get("/casework/status/")

    def upload(self, *, raw=b"not a wav", mime="audio/wav", **changes):
        fields = {
            "action": "attachment_upload",
            "revision": hidden(self.page, "revision"),
            "upload_proof": hidden(self.page, "upload_proof"),
            "synthetic_only": "yes",
            "csrfmiddlewaretoken": hidden(self.page, "csrfmiddlewaretoken"),
            "attachment": SimpleUploadedFile("capture.wav", raw, content_type=mime),
        }
        return self.client.post("/casework/status/", {**fields, **changes})

    def unchanged(self):
        self.assertEqual(CaseAttachment.objects.count(), 0)
        self.assertEqual(Case.objects.get().evidence_version, 1)

    def test_malformed_content_and_webm_mime_are_rejected(self):
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.upload(mime="audio/webm").status_code, 409)
        self.unchanged()

    def test_missing_consent_csrf_wrong_proof_and_stale_revision_are_rejected(self):
        from apps.answer_media.tests import audio_fixture

        self.assertEqual(self.upload(synthetic_only="no").status_code, 400)
        self.assertEqual(self.upload(csrfmiddlewaretoken="").status_code, 403)
        self.assertEqual(self.upload(upload_proof="0" * 64).status_code, 409)
        current = Case.objects.get()
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع اصطناعية إضافية",
            expected_revision=current.revision,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(self.upload(raw=audio_fixture()["raw"]).status_code, 409)
        self.assertEqual(CaseAttachment.objects.count(), 0)
        self.assertEqual(Case.objects.get().evidence_version, 2)
