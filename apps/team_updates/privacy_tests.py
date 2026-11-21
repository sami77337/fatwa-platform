"""A source-hidden event is absent before inbox counts and cannot be acknowledged."""

from django.test import TransactionTestCase, override_settings

from apps.ai_gateway.privacy_test_support import ClassifiedSources
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvent
from apps.data_quality import tests as quality_tests

from . import services
from .models import SeenUpdate


@override_settings(**quality_tests.FEATURES)
class TeamUpdatePrivacyTests(quality_tests.QualityFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.draft()
        self.answer = AnswerRevision.objects.get()
        self.event = CaseEvent.objects.get(action="SAVE_ANSWER")
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        self.privacy = ClassifiedSources(self, self.directory, self.directory.current.subject_id)
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ", "SEARCH"))

    def test_hidden_answer_event_is_omitted_and_cannot_create_seen_receipt(self):
        rows = services.read_inbox(**self.common)
        self.assertEqual([row["kind"] for row in rows], ["INTAKE"])
        with self.assertRaises(cases.CaseConflict):
            services.mark_seen(**self.case_common(), sequence=self.event.sequence)
        self.assertEqual(SeenUpdate.objects.count(), 0)
        self.privacy.classify("ANSWER", self.answer.pk, actions=("READ",))
        self.assertEqual(len(services.read_inbox(**self.common)), 2)
        self.assertTrue(services.mark_seen(**self.case_common(), sequence=self.event.sequence))

    def test_withdrawn_source_is_not_an_old_acknowledgement_capability(self):
        self.privacy.classify("ANSWER", self.answer.pk, actions=("READ",))
        rows = services.read_inbox(**self.common)
        self.assertEqual(rows[0]["kind"], "SAVE_ANSWER")
        self.privacy.authority.grants = {
            key: value
            for key, value in self.privacy.authority.grants.items()
            if dict(key)["target_kind"] != "ANSWER" or dict(key)["action"] != "READ"
        }
        with self.assertRaises(cases.CaseConflict):
            services.mark_seen(**self.case_common(), sequence=rows[0]["sequence"])
        self.assertEqual(SeenUpdate.objects.count(), 0)


@override_settings(**quality_tests.FEATURES)
class TeamAttachmentPrivacyTests(quality_tests.QualityFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.attach()
        self.attachment = CaseAttachment.objects.get()
        self.event = CaseEvent.objects.get(action="FOLLOWUP")
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        self.privacy = ClassifiedSources(self, self.directory, self.directory.current.subject_id)
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ", "SEARCH"))

    def test_attachment_event_retains_original_file_classification_before_inbox_and_seen(self):
        self.assertEqual([row["kind"] for row in services.read_inbox(**self.common)], ["INTAKE"])
        with self.assertRaises(cases.CaseConflict):
            services.mark_seen(**self.case_common(), sequence=self.event.sequence)
        self.assertEqual(SeenUpdate.objects.count(), 0)
        self.privacy.classify("ATTACHMENT", self.attachment.pk, actions=("READ",))
        rows = services.read_inbox(**self.common)
        self.assertEqual([row["kind"] for row in rows], ["FOLLOWUP", "INTAKE"])
        self.assertNotIn(self.attachment.filename, repr(rows))
        self.assertTrue(services.mark_seen(**self.case_common(), sequence=self.event.sequence))
