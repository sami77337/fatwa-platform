"""Same real campaign handlers, with a finite explicit synthetic MFA policy."""

import re
from datetime import timedelta

from django.test import Client, override_settings
from django.utils import timezone

from apps.operational_workspace.authority import OperationalAuthority
from tests.casework import test_http as http

from . import services, views
from .models import Factor, Proof, SessionAssurance
from .test_support import FEATURES, PASSWORDS, Directory, MfaFixture

NATIVE = {
    **{
        key: value
        for key, value in http.WEB_SETTINGS.items()
        if key not in {"MIDDLEWARE", "ROOT_URLCONF", "DATA_UPLOAD_MAX_NUMBER_FIELDS"}
    },
    **FEATURES,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
    "FATWA_OPERATIONAL_WORKSPACE_ENABLED": True,
}


def operational_authority(receipt):
    class Exact(OperationalAuthority):
        def projection_epoch(self):
            return "synthetic-mfa-admin-single-case-read-v1"

        def permits(self, **values):
            return (
                values["provider_id"] == Directory.provider_id
                and values["subject_id"] == "admin"
                and values["role"] == "ORGANIZER_ADMIN"
                and values["auth_epoch"] == "epoch-1"
                and values["case_ref"] == receipt["public_ref"]
                and values["action"]
                in {
                    "READ_QUEUE",
                    "READ_CASE",
                    "READ_METADATA",
                    "READ_DELIVERY",
                    "READ_PUBLICATION",
                    "READ_TRANSCRIPT",
                    "READ_CAPABILITY",
                }
                and values["resource"].get("case_id") == receipt["case_id"]
            )

        def grant_deadline(self, **values):
            return timezone.now() + timedelta(minutes=5) if self.permits(**values) else None

    return Exact()


class NativeFixture(MfaFixture):
    def setUp(self):
        super().setUp()
        self.enterContext(
            override_settings(
                FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=operational_authority(self.receipt)
            )
        )

    def primary(self, subject="mufti", *, surface="CASEWORK", client=None):
        client = client or Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        home = views.HOMES[surface]
        page = client.get(home + "login/")
        self.assertEqual(page.status_code, 200, page.content)
        page = http.post(client, home + "login/", {"credential": PASSWORDS[subject]}, page)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, 'id="mfa-pending"')
        self.assertNotContains(page, self.receipt["public_ref"])
        return client, page

    def challenge(self, client, surface="CASEWORK"):
        from django.http import HttpRequest

        request = HttpRequest()
        request.COOKIES = {key: value.value for key, value in client.cookies.items()}
        return request.get_signed_cookie(views.cookie(surface), salt=views.PENDING_SALT)

    def enroll_native(self, client, page, *, surface="CASEWORK"):
        page = http.post(client, views.PATHS[surface], {"action": "enroll"}, page)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, 'id="mfa-manual-key"')
        factor = Factor.objects.get(challenge_id=self.challenge(client, surface))
        return factor, page

    def verify_native(self, client, page, factor, *, surface="CASEWORK", offset=-1, expected=200):
        page = http.post(
            client,
            views.PATHS[surface],
            {"action": "verify", "code": self.otp(factor, offset=offset)},
            page,
        )
        self.assertEqual(page.status_code, expected, page.content)
        return page

    def enroll_login(self, subject="mufti", *, surface="CASEWORK"):
        client, page = self.primary(subject, surface=surface)
        factor, page = self.enroll_native(client, page, surface=surface)
        page = self.verify_native(client, page, factor, surface=surface)
        codes = re.findall(r"r-[a-f0-9]{64}", page.content.decode())
        self.assertEqual(len(codes), self.authority.rule.recovery_codes)
        proof = Proof.objects.get(factor=factor, purpose="ENROLL")
        assurance = SessionAssurance.objects.get(proof=proof)
        self.assertEqual(services.checked(assurance).session.subject_id, subject)
        return client, page, factor, codes
