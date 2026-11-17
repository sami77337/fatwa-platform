"""Inbox navigation remains scoped and never acknowledges current case evidence."""

from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services
from apps.requester_team_journey.tests import SETTINGS
from apps.requester_team_journey.views import PANEL_COOKIE
from apps.team_updates.models import SeenUpdate
from tests.casework.test_http import Directory, post


@override_settings(**{**SETTINGS, "ROOT_URLCONF": "config.campaign_urls"})
class CampaignUpdatesTests(TransactionTestCase):
    def test_inbox_open_new_followup_seen_and_panel_return_share_guarded_team(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        directory = Directory()
        case = services.intake_case(
            original_question="PRIVATE SYNTHETIC QUESTION",
            requester_id="campaign-updates",
            source_event_id="campaign-updates",
            idempotency_key="campaign-updates",
            synthetic_fixtures_only=True,
        )
        directory.grant(case["public_ref"])
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory):
            page = client.get("/casework/staff/login/")
            self.assertEqual(
                post(
                    client, "/casework/staff/login/", {"credential": directory.credential}, page
                ).status_code,
                303,
            )
            page = client.get("/casework/staff/")
            self.assertContains(page, "صندوق التحديثات")
            filters = {"action": "updates_filter", "state": "unread", "kind": "all", "page": "1"}
            page = post(client, "/casework/staff/", filters, page)
            self.assertEqual(page.context["unread"], 1)
            self.assertNotContains(page, "PRIVATE SYNTHETIC QUESTION")
            row = page.context["updates"][0]
            team = post(
                client, "/casework/staff/", {"action": "open", "case_ref": case["public_ref"]}, page
            )
            self.assertContains(team, 'id="queue-state"')
            self.assertContains(team, 'id="answer-text"')
            self.assertEqual(SeenUpdate.objects.count(), 0)
            services.add_followup(
                token=case["token"],
                text="PRIVATE NEW FACTS",
                expected_revision=1,
                synthetic_fixtures_only=True,
            )
            page = post(
                client,
                "/casework/staff/",
                {
                    "action": "updates_seen",
                    "case_ref": row["case_ref"],
                    "sequence": row["sequence"],
                    "proof": row["proof"],
                },
                page,
            )
            self.assertEqual(page.context["unread"], 1)
            self.assertEqual(page.context["updates"][0]["kind"], "FOLLOWUP")
            self.assertEqual(SeenUpdate.objects.count(), 1)
            self.assertEqual(client.get("/casework/staff/").context["unread"], 1)
            page = post(client, "/casework/staff/", {"action": "access_queue"}, page)
            self.assertContains(page, "لا توجد طلبات مفتوحة")
            self.assertEqual(
                post(client, "/casework/staff/", {"action": "journey_cases"}, page).status_code, 303
            )
            self.assertContains(client.get("/casework/staff/"), 'id="queue-heading"')
            # Preferences never authorize another browser, regardless of chosen panel.
            guest = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
            guest.cookies[PANEL_COOKIE] = "updates"
            self.assertEqual(guest.get("/casework/staff/").status_code, 403)
