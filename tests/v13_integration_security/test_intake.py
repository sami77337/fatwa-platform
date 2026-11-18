"""Late persistence failure and cross-browser replay of the shared intake adapter."""

from hashlib import sha256
from unittest.mock import patch

from django.db import IntegrityError
from django.test import Client, TransactionTestCase, override_settings

from apps.answer_media.tests import audio_fixture
from apps.case_attachments.models import CaseAttachment
from apps.casework.models import Case, CaseEvidence, CaseSource
from apps.casework_web.requester_intake import submit_intake
from apps.delivery_queue.models import RequesterTrackingToken
from tests.casework import test_v13_audio_wiring as audio


@override_settings(**audio.AUDIO_SETTINGS)
class IntakeFailureTests(TransactionTestCase):
    setUp = audio.InitialAudioTests.setUp
    upload = audio.InitialAudioTests.upload

    def test_late_database_failure_preserves_no_capability_and_retry_reuses_immutable_blob(self):
        attempted = []

        def fail(**kwargs):
            attempted.append(kwargs["id"])
            raise IntegrityError("synthetic late owner-row failure")

        with patch.object(CaseAttachment.objects, "create", side_effect=fail):
            result = self.upload()
        self.assertEqual(result.status_code, 503)
        self.assertEqual(len(attempted), 1)
        for model in (Case, CaseSource, CaseEvidence, CaseAttachment, RequesterTrackingToken):
            self.assertEqual(model.objects.count(), 0, model.__name__)
        path = self.storage.root / "objects" / (sha256(audio_fixture()["raw"]).hexdigest() + ".blob")
        self.assertEqual(path.read_bytes(), audio_fixture()["raw"])
        original_inode = path.stat().st_ino
        anonymous = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        denied = anonymous.get(f"/casework/status/attachments/{attempted[0]}/")
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(path.stat().st_ino, original_inode)
        self.assertEqual((Case.objects.count(), CaseAttachment.objects.count()), (1, 1))

    def test_other_requester_cannot_replay_same_intake_event_or_get_first_capability(self):
        from apps.casework.services import CaseConflict

        initial = submit_intake(question="synthetic", requester_id="first-synthetic",
                                request_id="same-source-event", attachment=audio_fixture())
        with self.assertRaises(CaseConflict):
            submit_intake(question="synthetic", requester_id="other-synthetic",
                          request_id="same-source-event", attachment=audio_fixture())
        replay = submit_intake(question="synthetic", requester_id="first-synthetic",
                               request_id="same-source-event", attachment=audio_fixture())
        self.assertEqual(replay["case_id"], initial["case_id"])
        self.assertIsNone(replay["token"])
        self.assertEqual((Case.objects.count(), CaseAttachment.objects.count()), (1, 1))
