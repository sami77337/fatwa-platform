"""Reuse the signed desk browser journey through the canonical staff navigation."""

from django.test import override_settings

from tests.case_delivery_desk import test_browser as contracts


@override_settings(ROOT_URLCONF="config.campaign_urls")
class CampaignDeliveryBrowserTests(contracts.DeliveryDeskBrowserTests):
    def submit(self, page, button):
        opening_session = button.inner_text() == "دخول المكتب"
        super().submit(page, button)
        if opening_session:
            self.assertEqual(page.locator("#queue-heading").count(), 1)
            super().submit(page, page.get_by_role("button", name="مكتب متابعة التسليم", exact=True))
