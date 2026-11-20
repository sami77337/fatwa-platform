"""Regression for late authorization changes while composing the private page."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.requester_portal import services as portal
from apps.requester_portal import views

from . import services as reports
from .tests import SETTINGS, ReportFixture


@override_settings(**SETTINGS)
class RequesterPageCompositionTests(ReportFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.requester = self.client_for()
        self.visible = portal.snapshot(token=self.a["token"], synthetic_fixtures_only=True)

    def assert_closed(self, response):
        self.assertEqual(response.status_code, 503, response.content)
        # Django's test signal retains contexts from discarded renders too;
        # inspect only the response bytes actually returned to the browser.
        self.assertContains(response, 'aria-label="تعذر تحديث القضية"', status_code=503)
        self.assertNotContains(response, self.visible["answer"]["text"], status_code=503)
        for part in self.visible["answer"]["parts"]:
            self.assertNotContains(response, part["id"], status_code=503)
        self.assertNotContains(response, 'id="content-reports"', status_code=503)

    def test_report_context_withdrawal_cannot_leave_earlier_answer_or_part_links(self):
        original = reports.requester_context

        def withdraw(**kwargs):
            self.directory.epoch = "revoked"
            context = original(**kwargs)
            self.assertEqual(context["targets"], [])
            return context

        with patch.object(reports, "requester_context", side_effect=withdraw):
            self.assert_closed(self.requester.get("/casework/status/"))

    def test_release_withdrawal_during_template_render_discards_generated_page(self):
        original = views.render

        def withdraw(*args, **kwargs):
            response = original(*args, **kwargs)
            if args[2].get("result"):
                self.directory.epoch = "revoked"
            return response

        with patch.object(views, "render", side_effect=withdraw):
            self.assert_closed(self.requester.get("/casework/status/"))

    def test_capability_change_during_render_rolls_back_and_discards_page(self):
        original = views.render

        def revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            if args[2].get("result"):
                cases.revoke_access(**self.staff(), requester_id="requester-a")
            return response

        with patch.object(views, "render", side_effect=revoke):
            self.assert_closed(self.requester.get("/casework/status/"))
        self.assertEqual(
            portal.snapshot(token=self.a["token"], synthetic_fixtures_only=True), self.visible
        )

    def test_unchanged_page_renders_answer_parts_and_reporting_together(self):
        response = self.requester.get("/casework/status/")
        self.assertContains(response, self.visible["answer"]["text"])
        self.assertEqual(response.context["result"], self.visible)
        self.assertEqual(len(response.context["reporting"]["targets"]), 3)
        self.assertContains(response, 'name="report_proof"')
        for part in self.visible["answer"]["parts"]:
            self.assertContains(response, part["id"])
