"""The native browser fixture must expose its real current-case entry form."""

from django.test import TransactionTestCase, override_settings

from apps.experimental_publication.tests_ui import Forms
from tests.casework.test_http import post

from .test_support import NATIVE_FEATURES, Fixture


@override_settings(**NATIVE_FEATURES)
class DestinationNavigationTests(Fixture, TransactionTestCase):
    def test_inbox_case_selection_reaches_destinations_with_current_read_permission(self):
        for subject in ("editor", "other", "publisher"):
            with self.subTest(subject=subject):
                client, inbox = self.login(subject)
                selected = next(
                    item
                    for item in Forms(inbox.content.decode()).forms
                    if item.get("action") == "open"
                    and item.get("case_ref") == self.receipt["public_ref"]
                )
                page = post(client, "/casework/staff/", selected, inbox)
                self.assertContains(page, "سجلات النشر المستقلة للوجهات")
                entries = [
                    item
                    for item in Forms(page.content.decode()).forms
                    if item.get("action") == "pd_open"
                ]
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0]["case_ref"], self.receipt["public_ref"])
                desk = post(client, "/casework/staff/", entries[0], page)
                self.assertContains(desk, 'id="destination-simulation"')
                self.assertContains(desk, 'id="mufti-original-question"')
                self.assertNotIn("PRIVATE SYNTHETIC", repr(desk.context["result"]["records"]))
                self.authority.denied.add((subject, "READ"))
                denied = post(client, "/casework/staff/", entries[0], page)
                self.assertEqual(denied.status_code, 409)
                self.assertNotContains(denied, self.first.body, status_code=409)
                self.authority.denied.clear()
