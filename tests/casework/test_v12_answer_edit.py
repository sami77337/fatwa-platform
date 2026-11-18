"""Native empty upload controls must permit versioned edits retaining original parts."""

from dataclasses import replace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings

from apps.answer_media import services
from apps.answer_media import tests as fixtures
from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from tests.casework import test_v11_answer_parts as native
from tests.casework.test_http import WEB_SETTINGS, hidden


@override_settings(**{
    **WEB_SETTINGS, "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_ANSWER_MEDIA_ENABLED": True, "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
})
class NativeAnswerEditTests(TransactionTestCase):
    setUp = fixtures.AnswerMediaTests.setUp
    save = fixtures.AnswerMediaTests.save
    open_editor = native.NativePartRevisionTests.open_editor

    def fields(self, page, **overrides):
        return {
            "action": "answer_media_save", "case_ref": self.receipt["public_ref"],
            "revision": hidden(page, "revision"),
            "evidence_version": hidden(page, "evidence_version"),
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            "text": "صياغة بشرية معدّلة مع بقاء الأصول", "retain": "yes",
            "synthetic_only": "yes", "answer_file": "", **overrides,
        }

    def test_returned_multipart_edit_without_new_file_preserves_originals_and_history(self):
        self.save(files=[fixtures.audio_fixture(), {
            "raw": b"synthetic existing file", "filename": "existing.txt", "media_type": "text/plain",
        }])
        before = services.staff_snapshot(**self.common)["latest_package"]
        current = cases.read_case(**self.common)
        cases.record_decision(
            **self.common, answer_id=before["answer_id"], action="RETURN_FOR_CHANGES",
            expected_revision=current["revision"], expected_evidence_version=current["evidence_version"],
            note="تعديل بشري مطلوب",
        )
        originals = [(part.pk, part.sha256, part.original) for part in AnswerPart.objects.all()]
        page = self.open_editor()
        response = self.staff.post("/casework/staff/", self.fields(page))
        self.assertEqual(response.status_code, 200, response.content[:300])
        after = services.staff_snapshot(**self.common)["latest_package"]
        self.assertNotEqual(after["answer_id"], before["answer_id"])
        self.assertFalse(after["approved"])
        self.assertEqual([(p["filename"], p["sha256"]) for p in after["parts"][1:]],
                         [(p["filename"], p["sha256"]) for p in before["parts"][1:]])
        for pk, digest, raw in originals:
            old = AnswerPart.objects.get(pk=pk)
            self.assertEqual((old.sha256, old.original), (digest, raw))
        revision = cases.read_case(**self.common)["revision"]
        self.assertEqual(self.staff.post("/casework/staff/", self.fields(page)).status_code, 409)
        self.assertEqual(cases.read_case(**self.common)["revision"], revision)

    def test_unknown_duplicate_nonempty_and_mixed_file_fields_never_save(self):
        self.save()
        page = self.open_editor()
        before = cases.read_case(**self.common)["revision"]
        for changes in (
            {"answer_file": "existing.txt"}, {"answer_file": ["", ""]}, {"unexpected": ""},
            {"answer_file": ["", SimpleUploadedFile("new.txt", b"synthetic", "text/plain")]},
        ):
            with self.subTest(changes=tuple(changes)):
                self.assertEqual(self.staff.post("/casework/staff/", self.fields(page, **changes)).status_code, 400)
                self.assertEqual(cases.read_case(**self.common)["revision"], before)

    def test_empty_upload_edit_still_requires_csrf_and_current_scope(self):
        self.save()
        page = self.open_editor()
        self.assertEqual(self.staff.post("/casework/staff/", self.fields(page, csrfmiddlewaretoken="")).status_code, 403)
        self.directory.current = replace(self.directory.current, case_keys=frozenset())
        self.assertEqual(self.staff.post("/casework/staff/", self.fields(page)).status_code, 403)
