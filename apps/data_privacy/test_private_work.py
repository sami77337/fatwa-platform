"""Classification can remain pending without granting publication or an AI use."""

from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseSource
from apps.mufti_workspace import tests as workspace_tests
from tests.casework.test_http import post

from . import services, test_campaign
from .authority import UnclassifiedWorkGrant
from .campaign_test_support import FEATURES
from .catalog import locate
from .models import ClassificationRevision
from .private_work_test_support import WorkFixture


@override_settings(**{**FEATURES, "FATWA_MUFTI_WORKSPACE_ENABLED": True})
class UnclassifiedWorkTests(WorkFixture, TransactionTestCase):
    login = test_campaign.CampaignPrivacyTests.login
    mutation = workspace_tests.MuftiWorkspaceTests.mutation

    def classify(self, *, level):
        rows = services.history(self.target)
        self.allow(self.target, level, "CLASSIFY", previous_level=rows[-1].level if rows else "")
        return services.classify(
            kind="CASE",
            identifier=self.target.identifier,
            level=level,
            note="قرار تصنيف بشري اصطناعي مستقل",
            expected_digest=rows[-1].digest if rows else services.ZERO,
            expected_source_digest=self.target.source_digest,
            request_key=uuid4(),
            provider=self.directory,
            subject_id=self.principal().subject_id,
            synthetic_fixtures_only=True,
        )

    def test_actual_native_human_draft_and_approval_need_no_classification_or_transcript(self):
        self.permit_private_work()
        before = list(CaseSource.objects.values())
        self.client = self.login("mufti", "/casework/staff/")
        page = post(
            self.client,
            "/casework/staff/",
            {"action": "case_workspace", "case_ref": self.receipt["public_ref"]},
            self.client.get("/casework/staff/"),
        )
        self.assertEqual(page.status_code, 200, page.content)
        text = "جواب بشري مستقل <script> محفوظ كما أدخله المفتي."
        page = self.mutation(page, "draft", text=text)
        self.assertEqual(page.status_code, 200, page.content)
        answer = AnswerRevision.objects.get()
        self.assertEqual(answer.text, text)
        page = self.mutation(page, "approve", answer_id=str(answer.pk), note="قرار بشري")
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(Case.objects.get().approved_answer_id, answer.pk)
        self.assertEqual(ClassificationRevision.objects.count(), 0)
        self.assertEqual(list(CaseSource.objects.values()), before)

    def test_private_read_never_grants_other_purposes_or_requester_access(self):
        self.permit_private_work()
        value = services.require("CASE", self.target.identifier, principal=self.principal())
        self.assertEqual((value["level"], value["revision"]), ("UNCLASSIFIED_WORK", 0))
        for action in ("SEARCH", "EXPORT", "PUBLISH", "AI", "VIEW_CLASSIFICATION", "CLASSIFY"):
            with self.subTest(action=action), self.assertRaises(services.PrivacyDenied):
                services.require(
                    "CASE", self.target.identifier, principal=self.principal(), action=action
                )
        for principal in (
            services.public_principal(),
            services.requester_principal(Case.objects.get(), cases._digest(self.receipt["token"])),
        ):
            with self.assertRaises(services.PrivacyDenied):
                services.require("CASE", self.target.identifier, principal=principal)
        self.assertFalse(ClassificationRevision.objects.exists())

    def test_existing_classification_never_uses_the_private_work_fallback(self):
        self.permit_private_work()
        self.classify(level="RESTRICTED")
        with self.assertRaises(services.PrivacyDenied):
            cases.read_case(**self.common)
        self.allow(self.target, "RESTRICTED", "READ")
        self.assertEqual(cases.read_case(**self.common)["public_ref"], self.receipt["public_ref"])
        with (
            override_settings(FATWA_DATA_PRIVACY_ENABLED=False),
            self.assertRaises(services.PrivacyDenied),
        ):
            cases.read_case(**self.common)

    def test_late_classification_or_policy_change_withholds_prior_unclassified_projection(self):
        self.permit_private_work()
        with self.assertRaises(services.PrivacyDenied), services.projection():
            cases.read_case(**self.common)
            self.classify(level="PUBLIC")
        self.assertFalse(ClassificationRevision.objects.exists())
        with self.assertRaises(services.PrivacyDenied), services.projection():
            cases.read_case(**self.common)
            self.authority.work.clear()
        self.permit_private_work()
        self.assertEqual(cases.read_case(**self.common)["public_ref"], self.receipt["public_ref"])

    def test_wrong_binding_and_late_actual_identity_revocation_fail_closed(self):
        self.permit_private_work()
        with (
            patch.object(
                self.authority,
                "authorize_unclassified_work",
                return_value=UnclassifiedWorkGrant(self.authority.until, "0" * 64),
            ),
            self.assertRaises(services.PrivacyDenied),
        ):
            cases.read_case(**self.common)
        with self.assertRaises(services.PrivacyDenied), services.projection():
            cases.read_case(**self.common)
            self.directory.identities["mufti"] = replace(
                self.directory.identities["mufti"], active=False
            )

    def test_case_work_grant_cannot_approve_an_answer_without_its_exact_private_read(self):
        self.permit_private_work()
        result = cases.save_answer(
            **self.common, text="جواب بشري", expected_revision=1, expected_evidence_version=1
        )
        answer = AnswerRevision.objects.get()
        self.authority.creators.clear()
        with self.assertRaises(services.PrivacyDenied):
            cases.record_decision(
                **self.common,
                answer_id=answer.pk,
                action="APPROVE",
                expected_revision=result["revision"],
                expected_evidence_version=result["evidence_version"],
            )
        self.assertEqual(CaseDecision.objects.count(), 0)
        self.assertEqual(ClassificationRevision.objects.count(), 0)
        self.assertEqual(locate("ANSWER", answer.pk).identifier, str(answer.pk))
