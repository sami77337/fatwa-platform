"""Test-only signer and directory; never imported by the desk application."""

import json

from django.conf import settings
from django.test import override_settings

from apps.case_delivery_desk.views import _request
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import WEB_SETTINGS as CASE_WEB_SETTINGS

WEB_SETTINGS = {
    **CASE_WEB_SETTINGS,
    "ROOT_URLCONF": "apps.case_delivery_desk.urls",
    "INSTALLED_APPS": [*settings.INSTALLED_APPS, "apps.case_delivery_desk"],
}
CREDENTIAL = "synthetic-credential-with-32-characters"


class DeskFixture(CaseDeliveryFixture):
    def setUp(self):
        super().setUp()
        self.approved = self.approve()
        self.foreign = self.intake("foreign")
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_CASE_DELIVERY_APPROVAL_VERIFIER=self.approval_verifier,
            FATWA_CASE_DELIVERY_PROVIDER_VERIFIER=self.channel_verifier,
            SECURE_REFERRER_POLICY="same-origin",
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def signed_response(self):
        request = _request(self.staff(), max_chars=24, split=True)
        from dataclasses import asdict

        return json.dumps(
            {
                "request_sha256": request["request_sha256"],
                "receipt": asdict(self.receipt(request)),
            }
        )
