"""Classification filters diagnostics before rows, pagination and totals."""

from django.test import TransactionTestCase, override_settings

from apps.ai_gateway.privacy_test_support import ClassifiedSources
from apps.casework.models import AnswerRevision
from apps.data_privacy.services import PrivacyDenied

from . import services
from . import tests as quality_tests


@override_settings(**quality_tests.FEATURES)
class QualityPrivacyTests(quality_tests.QualityFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        self.privacy = ClassifiedSources(self, self.directory, self.directory.current.subject_id)

    def test_unclassified_and_unsearchable_cases_do_not_enter_rows_or_counts(self):
        result = self.inspect()
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["page_case_count"], 0)
        self.assertIsNone(result["next_page"])
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ",))
        self.assertEqual(self.inspect()["rows"], [])
        self.privacy.allow("CASE", self.receipt["case_id"], "SEARCH")
        self.assertEqual(self.inspect()["page_case_count"], 1)

    def test_direct_hidden_case_denies_and_late_withdrawal_discards_projection(self):
        with self.assertRaises(PrivacyDenied):
            self.inspect(case_ref=self.receipt["public_ref"])
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ", "SEARCH"))
        with self.assertRaises(PrivacyDenied):
            with services.projection(**self.common) as result:
                self.assertEqual(result["page_case_count"], 1)
                self.privacy.authority.grants.clear()


@override_settings(**quality_tests.FEATURES)
class QualityAnswerPrivacyTests(quality_tests.QualityFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.draft()
        self.answer = AnswerRevision.objects.get()
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        self.privacy = ClassifiedSources(self, self.directory, self.directory.current.subject_id)
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ", "SEARCH"))

    def test_hidden_child_does_not_generate_a_technical_finding_or_source_count(self):
        result = self.inspect()
        self.assertEqual(self.state(result, "canonical"), "NOT_CHECKED")
        self.assertEqual(result["technical_count"], 0)
        self.assertEqual(len(result["rows"][0]["checks"]), 1)
        self.assertNotIn(str(self.answer.pk), repr(result))
        self.assertNotIn(self.answer.text, repr(result))
        self.privacy.classify("ANSWER", self.answer.pk, actions=("READ",))
        self.assertEqual(self.state(self.inspect(), "canonical"), "OK")
