"""Current classification has an AI grant independent from reading and citing."""

from django.db import connection
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.data_privacy.services import PrivacyDenied
from apps.research_library.models import LibraryVersion

from . import services
from .models import CandidateBatch, GatewayOutcome, GatewayRun
from .privacy_test_support import ClassifiedSources
from .test_support import FEATURES, GatewayFixture


@override_settings(**FEATURES)
class CitationPrivacyTests(GatewayFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.privacy = ClassifiedSources(self, self.directory, "editor")
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ", "SEARCH"))
        self.privacy.classify(
            "LIBRARY_VERSION", self.material["version_id"], actions=("READ", "SEARCH")
        )

    def ai_grants(self):
        return [
            self.privacy.allow("CASE", self.receipt["case_id"], "AI"),
            self.privacy.allow("LIBRARY_VERSION", self.material["version_id"], "AI"),
        ]

    def test_read_and_citation_rights_do_not_authorize_ai_context(self):
        with self.assertRaises(PrivacyDenied):
            self.request()
        self.assertEqual(self.ai_provider.calls, [])
        self.assertEqual(GatewayRun.objects.count(), 0)
        self.privacy.allow("CASE", self.receipt["case_id"], "AI")
        with self.assertRaises(PrivacyDenied):
            self.request()
        self.assertEqual(self.ai_provider.calls, [])

    def test_classified_source_runs_outside_transaction_without_rewriting_original(self):
        self.ai_grants()
        original = list(LibraryVersion.objects.values())
        state = []
        self.ai_provider.hook = lambda: state.append(connection.in_atomic_block)
        row = self.request()
        self.assertEqual(state, [False])
        self.assertEqual(row["status"], "SUCCEEDED")
        self.assertEqual(list(LibraryVersion.objects.values()), original)
        with services.read_boundary(**self.common, run_id=row["id"]) as result:
            self.assertEqual(result["candidates"][0]["selected"], self.source_text[:12])

    def test_withdrawal_during_provider_prevents_batch_and_subsequent_display(self):
        key = self.ai_grants()[1]
        self.ai_provider.hook = lambda: self.privacy.authority.grants.pop(key)
        with self.assertRaises(cases.CaseConflict):
            self.request()
        self.assertEqual(len(self.ai_provider.calls), 1)
        self.assertEqual(CandidateBatch.objects.count(), 0)
        self.assertEqual(GatewayOutcome.objects.get().status, "REVOKED")
        with self.assertRaises(cases.CaseConflict):
            with services.read_boundary(**self.common, run_id=GatewayRun.objects.get().pk):
                self.fail("withdrawn AI source must not be rendered")

    def test_classification_policy_change_between_transactions_cannot_reuse_result(self):
        self.ai_grants()
        key = self.privacy.allow("CASE", self.receipt["case_id"], "EXPORT")
        grant = self.privacy.authority.grants.pop(key)
        self.ai_provider.hook = lambda: self.privacy.authority.grants.__setitem__(key, grant)
        with self.assertRaises(cases.CaseConflict):
            self.request()
        self.assertEqual(CandidateBatch.objects.count(), 0)
        self.assertEqual(GatewayOutcome.objects.get().status, "REVOKED")

    def test_withdrawn_ai_permission_after_success_blocks_original_and_selection(self):
        key = self.ai_grants()[1]
        row = self.request()
        self.privacy.authority.grants.pop(key)
        with self.assertRaises(PrivacyDenied):
            with services.read_boundary(**self.common, run_id=row["id"]):
                self.fail("a saved derived batch does not authorize its current source")


@override_settings(**FEATURES)
class AnswerSourcePrivacyTests(GatewayFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.source_receipt, source_base = self.second_case()
        cases.save_answer(
            **source_base,
            text="جواب بشري اصطناعي مستقل محفوظ كمصدر دقيق",
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.answer = AnswerRevision.objects.get(case_id=self.source_receipt["case_id"])
        cases.record_decision(
            **source_base,
            answer_id=self.answer.pk,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        self.ai_provider.source_id = str(self.answer.pk)
        self.gateway_authority.processing.add(
            ("ANSWER", str(self.answer.pk), self.answer.text_sha256)
        )
        self.privacy = ClassifiedSources(self, self.directory, "editor")
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ", "AI"))
        self.privacy.classify("CASE", self.source_receipt["case_id"], actions=("READ",))
        self.privacy.classify("ANSWER", self.answer.pk, actions=("AI",))

    def test_cross_case_source_keeps_its_independent_ai_processing_permission(self):
        self.privacy.allow("ANSWER", self.answer.pk, "READ")
        with self.assertRaises(PrivacyDenied):
            self.request(selection="ANSWER:" + str(self.answer.pk))
        self.assertEqual(self.ai_provider.calls, [])
        self.privacy.allow("CASE", self.source_receipt["case_id"], "AI")
        self.assertEqual(
            self.request(selection="ANSWER:" + str(self.answer.pk))["status"], "SUCCEEDED"
        )

    def test_ai_permission_does_not_substitute_for_reading_the_approved_answer(self):
        self.privacy.allow("CASE", self.source_receipt["case_id"], "AI")
        with self.assertRaises(PrivacyDenied):
            self.request(selection="ANSWER:" + str(self.answer.pk))
        self.assertEqual(self.ai_provider.calls, [])
        self.privacy.allow("ANSWER", self.answer.pk, "READ")
        self.assertEqual(
            self.request(selection="ANSWER:" + str(self.answer.pk))["status"], "SUCCEEDED"
        )
