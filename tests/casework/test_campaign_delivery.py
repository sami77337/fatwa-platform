"""Run every delivery desk HTTP boundary through the shared team dispatcher."""

from django.test import override_settings

from tests.case_delivery_desk import test_http as contracts
from tests.casework.test_http import post


@override_settings(ROOT_URLCONF="config.campaign_urls")
class CampaignDeliveryTests(contracts.DeliveryDeskHTTPTests):
    def login(self):
        team = super().login()
        self.assertContains(team, 'id="queue-heading"')
        response = post(self.client, contracts.STAFF, {"action": "journey_delivery"}, team)
        self.assertEqual(response.status_code, 303)
        return self.client.get(contracts.STAFF)

    def test_delivery_panel_returns_to_current_team_editor(self):
        desk = self.login()
        self.assertContains(desk, "مكتب متابعة التسليم")
        self.assertEqual(
            post(self.client, contracts.STAFF, {"action": "journey_cases"}, desk).status_code, 303
        )
        team = self.client.get(contracts.STAFF)
        team = self.action(team, "open")
        self.assertContains(team, 'id="answer-text"')
        self.assertNotContains(team, 'id="prepare-form"')
