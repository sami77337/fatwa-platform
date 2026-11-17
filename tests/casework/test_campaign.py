"""Real PostgreSQL cross-slice journeys on a single closed URL/settings profile."""

from dataclasses import replace

from django.test import SimpleTestCase, override_settings
from django.urls import resolve, reverse

from apps.casework import services
from apps.casework.delivery import prepare_case_delivery, requester_delivery_status
from apps.casework_web import requester_intake
from apps.requester_team_journey.views import requester
from apps.team_workspace import views as team_views
from apps.team_workspace.campaign import staff
from tests.casework import test_http as http_contracts
from tests.casework import test_requester_workspace as requester_contracts
from tests.casework.test_http import hidden, post


class CampaignProfileTests(SimpleTestCase):
    def test_explicit_profile_preserves_closed_identity_recovery_and_guard(self):
        from config.settings import campaign_review, casework_review

        expected_middleware = [
            "apps.library_preview.guard.PreviewCompositionGuard"
            if item == "apps.casework_web.guard.CaseworkGuard"
            else item
            for item in casework_review.MIDDLEWARE
        ]
        self.assertEqual(campaign_review.MIDDLEWARE, expected_middleware)
        from apps.casework_web.guard import CaseworkGuard
        from apps.library_preview.guard import PreviewCompositionGuard

        self.assertIsInstance(PreviewCompositionGuard(lambda request: None).casework, CaseworkGuard)
        self.assertFalse(campaign_review.FATWA_LIBRARY_PREVIEW_ENABLED)
        self.assertIsNone(campaign_review.FATWA_LIBRARY_PREVIEW_POLICY)
        self.assertFalse(campaign_review.FATWA_REQUESTER_PORTAL_ENABLED)
        self.assertIsNone(campaign_review.FATWA_CASEWORK_IDENTITY_PROVIDER)
        self.assertIsNone(campaign_review.FATWA_CASEWORK_RECOVERY_RESOLVER)
        self.assertEqual(campaign_review.ROOT_URLCONF, "config.campaign_urls")
        self.assertEqual(casework_review.ROOT_URLCONF, "apps.casework_web.urls")
        expected = {
            "requester_intake": requester_intake.intake,
            "casework_intake": requester_intake.intake,
            "requester_workspace": requester,
            "casework_status": requester,
            "casework_staff": staff,
            "casework_css": team_views.stylesheet,
        }
        for name, view in expected.items():
            self.assertIs(
                resolve(
                    reverse(name, urlconf="config.campaign_urls"), urlconf="config.campaign_urls"
                ).func,
                view,
            )


@override_settings(ROOT_URLCONF="config.campaign_urls")
class CampaignJourneyTests(requester_contracts.RequesterWorkspaceTests):
    """Reuse all nine requester isolation regressions on the integrated routes."""

    login = http_contracts.CaseworkHTTPTests.login
    open_case = http_contracts.CaseworkHTTPTests.open_case
    mutation = http_contracts.CaseworkHTTPTests.mutation

    def setUp(self):
        super().setUp()
        identity = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        identity.enable()
        self.addCleanup(identity.disable)

    def test_requester_team_clarify_return_approve_delivery_boundary_and_revocation(self):
        requester = self.client
        case, token, *_ = self.intake()
        other, _, *_ = self.intake(self.browser(), question="OUTSIDE SCOPE QUESTION")
        self.directory.grant(case.public_ref)
        self.client = self.browser()
        page = self.login()
        self.assertContains(page, "مساحة الشيخ والفريق")
        self.assertNotContains(page, other.public_ref)
        self.assertEqual(requester.get("/casework/staff/").status_code, 403)
        page = self.open_case(case, page)
        page = self.mutation(page, "clarify", text="وضح المثال الاصطناعي")
        self.assertNotContains(page, 'name="action" value="draft"')
        status = requester.get("/casework/status/")
        self.assertContains(status, "وضح المثال الاصطناعي")
        self.assertEqual(self.followup(status, "تفصيل جديد", requester).status_code, 303)
        page = self.open_case(case, page)
        self.assertContains(page, "تفصيل جديد")
        page = self.mutation(page, "draft", text="PRIVATE FIRST DRAFT")
        page = self.mutation(
            page, "return", answer_id=hidden(page, "answer_id"), note="PRIVATE RETURN REASON"
        )
        self.assertContains(page, "PRIVATE RETURN REASON")
        page = self.mutation(page, "draft", text="PRIVATE REVISED ANSWER")
        page = self.mutation(page, "approve", answer_id=hidden(page, "answer_id"), note="")
        self.assertEqual(page.status_code, 200)
        status = requester.get("/casework/status/")
        self.assertContains(status, "اكتملت مراجعة الجواب")
        for text in (
            "PRIVATE FIRST DRAFT",
            "PRIVATE RETURN REASON",
            "PRIVATE REVISED ANSWER",
            "الجواب متاح",
            token,
        ):
            self.assertNotContains(status, text)
        common = self.common(case)
        prepared = prepare_case_delivery(**common)
        self.assertTrue(prepared)
        evidence = requester_delivery_status(token=token, synthetic_fixtures_only=True)
        self.assertFalse(evidence["read_confirmed"])
        # A real requester followup invalidates the exact Mufti-approved answer.
        self.assertEqual(self.followup(status, "تغيرت الوقائع", requester).status_code, 303)
        with self.assertRaises(services.CaseConflict):
            prepare_case_delivery(**common)
        page = self.open_case(case, page)
        self.assertContains(page, 'id="stale-answer"')
        self.assertNotContains(page, 'value="approve"')
        self.directory.current = replace(self.directory.current, role="ORGANIZER")
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)
        self.assertEqual(case.answers.count(), 2)

    def test_same_browser_requester_close_invalidates_staff_cookie_without_revoking_token(self):
        case, token, *_ = self.intake()
        self.directory.grant(case.public_ref)
        self.login()
        # Staff login rotates CSRF: requester access must be explicitly reopened.
        self.assertEqual(self.unlock(token).status_code, 303)
        page = self.client.get("/casework/status/")
        self.assertEqual(
            post(self.client, "/casework/status/", {"action": "leave"}, page).status_code, 303
        )
        self.assertEqual(self.client.get("/casework/staff/").status_code, 403)
        self.assertEqual(self.unlock(token).status_code, 303)
