"""Session security on the actual shared campaign routes and guard composition."""

import time
from hashlib import sha256
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.casework_web.guard import LIMITS
from apps.casework_web.models import ThrottleBucket
from tests.casework import test_http as http

from .models import FreshProof, ProofUse, SessionRevocation
from .test_support import CREDENTIALS, FEATURES, SessionFixture, operational_authority

CAMPAIGN = {
    key: value for key, value in FEATURES.items() if key not in {"ROOT_URLCONF", "MIDDLEWARE"}
}
CAMPAIGN["ROOT_URLCONF"] = "config.campaign_urls"


@override_settings(**CAMPAIGN)
class CampaignSessionTests(SessionFixture, TransactionTestCase):
    def test_real_staff_and_operations_navigation_and_server_logout(self):
        self.assertContains(self.client.get("/casework/staff/"), 'href="/casework/sessions/"')
        with override_settings(
            FATWA_OPERATIONAL_WORKSPACE_ENABLED=True,
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=operational_authority(self.receipt),
        ):
            admin = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
            page = admin.get("/casework/operations/login/")
            self.assertEqual(
                http.post(
                    admin, "/casework/operations/login/", {"credential": CREDENTIALS["admin"]}, page
                ).status_code,
                303,
            )
            page = admin.get("/casework/operations/")
            self.assertContains(page, 'href="/casework/operations/sessions/"')
            self.assertEqual(admin.get("/casework/operations/sessions/").status_code, 200)
            copied = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
            copied.cookies = admin.cookies.copy()
            self.assertEqual(
                http.post(admin, "/casework/operations/logout/", {}, page).status_code, 303
            )
            self.assertEqual(SessionRevocation.objects.count(), 1)
            # The existing operational boundary represents an unavailable
            # current actor as a conflict; it still releases no queue data.
            self.assertEqual(copied.get("/casework/operations/").status_code, 409)
            self.assertEqual(self.client.get("/casework/staff/").status_code, 200)

    def test_native_fresh_confirmation_is_separate_and_revokes_only_the_selected_session(self):
        selected = self.select()
        self.assertEqual(selected.status_code, 200)
        verified = self.fresh(selected)
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(FreshProof.objects.count(), 1)
        self.assertEqual(SessionRevocation.objects.count(), 0)
        response = self.revoke(verified)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], "/casework/sessions/")
        self.assertEqual(ProofUse.objects.count(), 1)
        self.assertEqual(SessionRevocation.objects.count(), 1)
        self.assertEqual(self.other_client.get("/casework/staff/").status_code, 403)
        self.assertEqual(self.client.get("/casework/staff/").status_code, 200)

    def test_both_session_post_routes_share_the_unchanged_credential_budget(self):
        now = time.time()
        window = int(now) // 60
        key = sha256(b"127.0.0.1|login").hexdigest()
        used = (
            ThrottleBucket.objects.filter(key=key, window=window)
            .values_list("requests", flat=True)
            .first()
            or 0
        )
        routes = ("/casework/sessions/", "/casework/operations/sessions/")
        with patch("apps.casework_web.guard.time.time", return_value=now):
            for index in range(LIMITS["login"] - used):
                response = http.post(
                    self.client, routes[index % 2], {"action": "invalid"}, self.page
                )
                self.assertIn(response.status_code, {400, 403})
            for route in routes:
                self.assertEqual(
                    http.post(self.client, route, {"action": "invalid"}, self.page).status_code, 429
                )
        self.assertEqual(FreshProof.objects.count(), 0)
        self.assertEqual(SessionRevocation.objects.count(), 0)
        self.assertEqual(self.client.get("/casework/sessions/").status_code, 200)
