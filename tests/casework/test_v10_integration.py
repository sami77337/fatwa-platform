"""Shared V10 routing/frame boundaries over the canonical synthetic database."""

from django.test import Client, TransactionTestCase, override_settings

from apps.casework.models import CaseEvent
from apps.mufti_workspace import tests as workspace_fixtures
from apps.requester_team_journey.views import PANEL_COOKIE
from tests.casework.test_http import post


@override_settings(
    FATWA_MUFTI_WORKSPACE_ENABLED=True,
    FATWA_CASEWORK_WEB_ENABLED=True,
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
    FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED=True,
    FATWA_COMPOSITE_DELIVERY_ENABLED=True,
)
class ConnectedCompositionTests(TransactionTestCase):
    setUp = workspace_fixtures.MuftiWorkspaceTests.setUp
    open = workspace_fixtures.MuftiWorkspaceTests.open

    def test_explicit_case_navigation_ignores_legacy_panel_cookie_and_stays_scoped(self):
        self.client.cookies[PANEL_COOKIE] = "delivery"
        before = CaseEvent.objects.count()
        page = self.open()
        self.assertContains(page, 'id="mufti-case-reference"')
        self.assertEqual(
            page.context["mufti_workspace"]["case"]["case_id"], self.receipt["case_id"]
        )
        self.assertEqual(page.cookies[PANEL_COOKIE].value, "cases")
        self.assertEqual(CaseEvent.objects.count(), before)
        timeline = post(
            self.client,
            "/casework/staff/",
            {
                "action": "source_timeline",
                "case_ref": self.receipt["public_ref"],
            },
            page,
        )
        self.assertEqual(timeline.status_code, 200, timeline.content)
        self.assertContains(timeline, 'id="mufti-case-reference"')
        self.assertEqual(timeline.context["mufti_workspace"]["active"], "origins")

    def test_new_native_denial_pages_do_not_retry_the_failed_private_frame(self):
        foreign = workspace_fixtures.new_case("FOREIGN PRIVATE QUESTION")
        for action in ("composite_open", "source_timeline"):
            with self.subTest(action=action):
                response = post(
                    self.client,
                    "/casework/staff/",
                    {
                        "action": action,
                        "case_ref": foreign["public_ref"],
                    },
                    self.queue,
                )
                self.assertIn(response.status_code, {403, 404, 409})
                self.assertNotIn(b"FOREIGN PRIVATE QUESTION", response.content)
                self.assertNotIn(b"mufti-case-reference", response.content)
        self.directory.current = None
        for action in ("composite_open", "source_timeline"):
            response = post(
                self.client,
                "/casework/staff/",
                {
                    "action": action,
                    "case_ref": self.receipt["public_ref"],
                },
                self.queue,
            )
            self.assertEqual(response.status_code, 403, response.content)
            self.assertNotIn(b"mufti-case-reference", response.content)

    def test_portal_opt_in_preserves_existing_route_and_never_gets_staff_context(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with override_settings(FATWA_REQUESTER_PORTAL_ENABLED=False):
            page = client.get("/casework/status/")
            self.assertContains(page, "مساحة متابعة سؤالي")
        with override_settings(FATWA_REQUESTER_PORTAL_ENABLED=True):
            page = client.get("/casework/status/")
            self.assertContains(page, "بوابة السائل الخاصة")
            response = post(
                client,
                "/casework/status/",
                {
                    "action": "unlock",
                    "token": self.receipt["token"],
                },
                page,
            )
            self.assertEqual(response.status_code, 303)
            page = client.get("/casework/status/")
            self.assertContains(page, 'data-answer-state="UNDER_REVIEW"')
            self.assertNotContains(page, 'id="mufti-case-reference"')
            self.assertNotContains(page, "مكتب استقبال المصادر")
            self.assertNotContains(page, "سجل القضية المتصل")

    def test_library_guard_does_not_exempt_private_routes_or_create_staff_selection(self):
        response = self.client.get("/library-preview/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("fatwa_casework_csrf", response.cookies)
        blocked = self.client.get("/casework/staff/?case_ref=" + self.receipt["public_ref"])
        self.assertEqual(blocked.status_code, 400)
        self.assertNotIn(b"mufti-case-reference", blocked.content)
        denied = self.client.get("/casework/staff/", REMOTE_ADDR="203.0.113.10")
        self.assertEqual(denied.status_code, 403)
