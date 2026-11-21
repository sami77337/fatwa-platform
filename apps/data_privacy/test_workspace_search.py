"""The native queue admits SEARCH before matching private text or counts."""

from unittest.mock import patch
from uuid import uuid4

from django.test import TransactionTestCase, override_settings

from apps.case_attachments import tests as attachment_fixtures
from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.team_workspace import views
from tests.casework.test_http import post

from . import services, test_campaign
from .campaign_test_support import FEATURES
from .catalog import locate
from .models import ClassificationRevision
from .private_work_test_support import WorkFixture


@override_settings(**FEATURES)
class WorkspaceSearchPrivacyTests(WorkFixture, TransactionTestCase):
    login = test_campaign.CampaignPrivacyTests.login

    def setUp(self):
        super().setUp()
        self.client = self.login("mufti", "/casework/staff/")

    def admit(self, target, action="READ"):
        if not services.history(target):
            self.allow(target, "CONFIDENTIAL", "CLASSIFY")
            services.classify(
                kind=target.kind,
                identifier=target.identifier,
                level="CONFIDENTIAL",
                note="تصنيف بشري اصطناعي للبحث المستقل",
                expected_digest=services.ZERO,
                expected_source_digest=target.source_digest,
                request_key=uuid4(),
                provider=self.directory,
                subject_id="mufti",
                synthetic_fixtures_only=True,
            )
        return self.allow(target, "CONFIDENTIAL", action)

    def search(self, query):
        return post(
            self.client,
            "/casework/staff/",
            {"action": "filter", "state": "all", "query": query},
            self.client.get("/casework/staff/"),
        )

    def no_matches(self, page, *, total):
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(page.context["total"], total)
        self.assertEqual(page.context["matched_total"], 0)
        self.assertEqual(page.context["visible_total"], 0)
        self.assertNotContains(page, 'name="case_ref"')

    def test_private_pending_work_supports_inbox_but_never_text_or_reference_search(self):
        self.permit_private_work()
        self.assertContains(self.client.get("/casework/staff/"), self.receipt["public_ref"])
        for query in ("سؤال", self.receipt["public_ref"]):
            page = self.search(query)
            self.no_matches(page, total=0)
            self.assertTrue(all(row["count"] == 0 for row in page.context["filters"]))
            self.assertTrue(all(row["count"] == 0 for row in page.context["inboxes"]))
        self.assertEqual(cases.read_case(**self.common)["public_ref"], self.receipt["public_ref"])
        self.assertEqual(ClassificationRevision.objects.count(), 0)

    def test_classified_read_is_independent_and_late_search_revocation_withholds_response(self):
        self.admit(self.target)
        self.no_matches(self.search("سؤال"), total=0)
        key = self.admit(self.target, "SEARCH")
        self.assertEqual(self.search("سؤال").context["visible_total"], 1)
        render = views.render

        def render_then_revoke(*args, **kwargs):
            response = render(*args, **kwargs)
            self.authority.grants.pop(key, None)
            return response

        page = self.client.get("/casework/staff/")
        with patch.object(views, "render", side_effect=render_then_revoke):
            refused = post(
                self.client,
                "/casework/staff/",
                {"action": "filter", "state": "all", "query": "سؤال"},
                page,
            )
        self.assertEqual(refused.status_code, 404)
        self.assertNotContains(refused, self.receipt["public_ref"], status_code=404)
        self.assertEqual(cases.read_case(**self.common)["public_ref"], self.receipt["public_ref"])
        self.admit(self.target, "SEARCH")
        self.assertEqual(self.search("سؤال").context["visible_total"], 1)

    def test_case_search_does_not_search_a_readable_answer_without_exact_child_grant(self):
        self.permit_private_work()
        cases.save_answer(
            **self.common,
            text="answeruniqueseek",
            expected_revision=1,
            expected_evidence_version=1,
        )
        answer = locate("ANSWER", AnswerRevision.objects.get().pk)
        self.admit(self.target)
        self.admit(self.target, "SEARCH")
        self.admit(answer)
        self.assertEqual(len(cases.read_case(**self.common)["answers"]), 1)
        self.no_matches(self.search("answeruniqueseek"), total=1)
        self.admit(answer, "SEARCH")
        self.assertEqual(self.search("answeruniqueseek").context["visible_total"], 1)

    @override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=True)
    def test_copied_attachment_evidence_keeps_its_exact_search_gate(self):
        with override_settings(FATWA_DATA_PRIVACY_ENABLED=False):
            attached = attachment_fixtures.upload(self.receipt, filename="privateuniqueseek.txt")
        self.admit(self.target)
        self.admit(self.target, "SEARCH")
        attachment = locate("ATTACHMENT", attached["id"])
        self.admit(attachment)
        self.assertEqual(len(cases.read_case(**self.common)["followups"]), 1)
        self.no_matches(self.search("privateuniqueseek"), total=1)
        self.admit(attachment, "SEARCH")
        self.assertEqual(self.search("privateuniqueseek").context["visible_total"], 1)
