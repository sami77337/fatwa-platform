"""Exercise real campaign URL/render/guard wiring without integration patches."""

from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.casework.models import AnswerRevision
from apps.precise_citations.models import CitationSet
from tests.casework.test_http import hidden

from .test_http import NativeFixture, initial_state, states
from .test_support import FEATURES, GatewayFixture


@override_settings(**FEATURES)
class CampaignGatewayTests(GatewayFixture, TransactionTestCase):
    login = NativeFixture.login
    ai_post = NativeFixture.ai_post

    def test_actual_campaign_panel_routes_source_handoff_and_no_answer_write(self):
        self.assertEqual(settings.ROOT_URLCONF, "config.campaign_urls")
        client, opened = self.login()
        self.assertContains(opened, 'id="ai-citation-request"')
        script = client.get("/casework/ai-citations/panel.mjs")
        self.assertEqual(script.status_code, 200)
        self.assertIn("no-store", script["Cache-Control"])
        csrf = hidden(opened, "csrfmiddlewaretoken")
        result = self.ai_post(client, csrf, initial_state(opened))
        self.assertContains(result, 'data-run-status="SUCCEEDED"')
        source = self.ai_post(client, csrf, states(result)[0], "open")
        self.assertContains(source, "<mark>مصدر اصطناعي</mark>")
        selected = self.ai_post(client, csrf, states(source)[1], "select")
        self.assertContains(selected, 'data-ai-handoff="1"')
        self.assertEqual((AnswerRevision.objects.count(), CitationSet.objects.count()), (0, 0))

    def test_disabled_gateway_retains_manual_composer_and_denies_real_ai_routes(self):
        with override_settings(FATWA_AI_GATEWAY_ENABLED=False):
            client, opened = self.login()
            self.assertContains(opened, 'id="precise-text"')
            self.assertNotContains(opened, 'id="ai-citation-request"')
            self.assertEqual(client.get("/casework/ai-citations/panel.mjs").status_code, 404)
            refused = self.ai_post(client, hidden(opened, "csrfmiddlewaretoken"), "invalid")
            self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.ai_provider.calls, [])
