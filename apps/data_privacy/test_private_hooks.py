"""Classification changes actual case/portal/media reads, not only an enum API."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.private_media import links
from apps.private_media.test_signed_links import FEATURES, LinkAssertions, PrivateOriginalFixture
from tests.casework.test_http import post

from . import services
from .catalog import locate
from .test_support import Authority, PrivacyFixture


@override_settings(**FEATURES)
class PrivateClassificationTests(LinkAssertions, PrivateOriginalFixture, TransactionTestCase):
    principal = PrivacyFixture.principal
    allow = PrivacyFixture.allow
    classify = PrivacyFixture.classify

    def setUp(self):
        super().setUp()
        self.before = self.originals()
        self.authority = Authority()
        self.target = locate("CASE", self.receipt["case_id"])
        configured = override_settings(
            FATWA_DATA_PRIVACY_ENABLED=True, FATWA_DATA_PRIVACY_AUTHORITY=self.authority
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def admit(self, kind, identifier, *, requester=False, action="READ"):
        target = locate(kind, identifier)
        if not services.history(target):
            self.classify(target)
        principal = (
            services.requester_principal(
                cases.Case.objects.get(pk=self.receipt["case_id"]),
                cases._digest(self.receipt["token"]),
            )
            if requester
            else self.principal()
        )
        return self.allow(target, "CONFIDENTIAL", action, principal=principal)

    def admit_answer(self, *, requester=False):
        self.admit("CASE", self.target.identifier, requester=requester)
        self.admit("ANSWER", self.part.manifest.answer_id, requester=requester)
        for identifier in AnswerPart.objects.filter(manifest=self.part.manifest).values_list(
            "pk", flat=True
        ):
            self.admit("ANSWER_PART", identifier, requester=requester)

    def test_unclassified_case_is_absent_from_real_staff_queue_and_direct_reads(self):
        page = self.staff.get("/casework/staff/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, self.receipt["public_ref"])
        self.assertEqual(
            cases.list_cases(
                subject_id=self.directory.current.subject_id,
                provider=self.directory,
                synthetic_fixtures_only=True,
            ),
            [],
        )
        with self.assertRaises(services.PrivacyDenied):
            cases.read_case(**self.common)
        self.denied_file(self.staff.get(f"/casework/staff/answer-media/{self.part.pk}/"), self.raw)
        self.assertEqual(self.originals(), self.before)

    def test_case_public_label_never_exposes_unclassified_child_answer_or_filename(self):
        self.classify(level="PUBLIC")
        self.allow(self.target, "PUBLIC", "READ")
        current = cases.read_case(**self.common)
        self.assertEqual(current["answers"], [])
        self.assertEqual(current["followups"], [])
        self.assertIsNone(current["approved_answer_id"])
        self.assertNotIn("private-question.wav", repr(current))
        self.assertNotIn("PRIVATE synthetic original answer", repr(current))
        self.assertEqual(self.originals(), self.before)

    def test_real_request_directory_can_issue_media_only_after_exact_child_grants(self):
        self.admit_answer()
        url = self.answer_url(self.staff, "staff")
        self.exact_range(self.staff, url, self.raw)
        with override_settings(FATWA_DATA_PRIVACY_ENABLED=False):
            self.denied_file(self.staff.get(url), self.raw)
        self.exact_range(self.staff, url, self.raw)
        self.assertEqual(self.originals(), self.before)

    def test_requester_portal_counts_and_bytes_do_not_borrow_staff_classification_grants(self):
        self.admit_answer()
        self.admit("ATTACHMENT", self.attachment["id"])
        self.admit("CASE", self.target.identifier, requester=True)
        with override_settings(FATWA_REQUESTER_PORTAL_ENABLED=True):
            page = self.requester.get("/casework/status/")
            self.assertTemplateUsed(page, "requester_portal/portal.html")
            self.assertNotContains(page, 'id="authorized-answer"')
            self.assertNotContains(page, "private-question.wav")
            self.admit_answer(requester=True)
            self.admit("ATTACHMENT", self.attachment["id"], requester=True)
            page = self.requester.get("/casework/status/")
            self.assertContains(page, 'id="authorized-answer"')
            url = self.signed_url(page, f"/casework/status/answer-media/{self.part.pk}/")
            self.exact_range(self.requester, url, self.raw)
        self.assertEqual(self.originals(), self.before)

    def test_domain_last_callback_can_revoke_privacy_before_any_range_is_returned(self):
        self.admit_answer()
        url = self.answer_url(self.staff, "staff")
        target = locate("ANSWER_PART", self.part.pk)
        key = self.allow(target, "CONFIDENTIAL", "READ")
        original = links._range_response

        def build_then_revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            del self.authority.grants[key]
            return response

        with patch.object(links, "_range_response", side_effect=build_then_revoke):
            self.denied_file(self.staff.get(url, HTTP_RANGE="bytes=4-19"), self.raw)
        self.admit("ANSWER_PART", self.part.pk)
        self.exact_range(self.staff, url, self.raw)

    def test_privacy_callback_cannot_revoke_domain_identity_and_return_old_private_data(self):
        self.admit_answer()
        original = self.authority.authorize
        actor = self.directory.current

        def permit_then_revoke(**values):
            result = original(**values)
            if values["action"] == "READ":
                self.directory.grant("different-case-only")
            return result

        with patch.object(self.authority, "authorize", side_effect=permit_then_revoke):
            page = post(
                self.staff,
                "/casework/staff/",
                {
                    "action": "open",
                    "case_ref": self.receipt["public_ref"],
                },
                self.staff.get("/casework/staff/"),
            )
            self.assertNotIn(b"PRIVATE synthetic original answer", page.content)
            self.assertIn(page.status_code, (400, 403, 409))
        self.directory.current = actor
        self.assertEqual(self.originals(), self.before)
