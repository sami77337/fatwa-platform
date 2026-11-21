"""Current classification and current scan coverage are independent byte gates."""

from dataclasses import replace
from unittest.mock import patch

from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.data_privacy import test_support as privacy_fixtures
from apps.data_privacy.catalog import locate
from apps.private_media import links
from apps.private_media import test_signed_links as link_fixtures
from apps.staff_sessions import middleware as session_middleware
from apps.staff_sessions.authority import ReauthenticationRule, SessionAuthority
from apps.staff_sessions.models import Session
from config.settings import campaign_review

from . import services
from .test_support import configure_scanner

MIDDLEWARE = list(campaign_review.MIDDLEWARE)
for guard in (
    "apps.data_privacy.integration.PrivacyResponses",
    "apps.upload_security.middleware.UploadSecurityResponses",
):
    if guard not in MIDDLEWARE:
        MIDDLEWARE.insert(2, guard)
FEATURES = {
    **link_fixtures.FEATURES,
    "MIDDLEWARE": MIDDLEWARE,
    "FATWA_DATA_PRIVACY_ENABLED": False,
}


class NativeSessionAuthority(SessionAuthority):
    """Explicit fixture ISSUE/USE for this one native staff identity and surface."""

    def __init__(self, directory):
        actor = directory.current
        self.claims = {
            "provider_id": directory.provider_id,
            "subject_id": actor.subject_id,
            "role": actor.role,
            "auth_epoch": actor.auth_epoch,
        }
        self.hook = None

    def projection_epoch(self):
        return repr((self.claims, ("ISSUE", "USE"), "CASEWORK"))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        target = values["resource"]
        return (
            all(values[key] == value for key, value in self.claims.items())
            and values["action"] in {"ISSUE", "USE"}
            and target["surface"] == "CASEWORK"
            and all(
                target[key] == self.claims[key] for key in ("provider_id", "subject_id", "role")
            )
        )

    def reauthentication(self, **values):
        return ReauthenticationRule(True, 90)


@override_settings(**FEATURES)
class UploadPrivacyCompositionTests(
    link_fixtures.LinkAssertions, link_fixtures.PrivateOriginalFixture, TransactionTestCase
):
    principal = privacy_fixtures.PrivacyFixture.principal
    allow = privacy_fixtures.PrivacyFixture.allow
    classify = privacy_fixtures.PrivacyFixture.classify

    def setUp(self):
        # The fixture's actual native attachments and answer files are admitted
        # through the scanner, before classification is turned on for reading.
        configure_scanner(self)
        super().setUp()
        self.before = self.originals()
        self.authority = privacy_fixtures.Authority()
        configured = override_settings(
            FATWA_DATA_PRIVACY_ENABLED=True,
            FATWA_DATA_PRIVACY_AUTHORITY=self.authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.target = locate("CASE", self.receipt["case_id"])
        self.classify(self.target)
        self.allow(self.target, "CONFIDENTIAL", "READ")
        self.child = locate("ATTACHMENT", self.attachment["id"])
        self.classify(self.child)
        self.child_key = self.allow(self.child, "CONFIDENTIAL", "READ")
        self.url = self.attachment_url(self.staff, "staff")
        self.assertEqual(
            settings.MIDDLEWARE[0], "apps.platform_recovery.middleware.MaintenanceGuard"
        )
        self.assertTrue(set(campaign_review.MIDDLEWARE).issubset(settings.MIDDLEWARE))
        for guard in (
            "apps.data_privacy.integration.PrivacyResponses",
            "apps.upload_security.middleware.UploadSecurityResponses",
            "apps.private_media.links.PrivateMediaResponses",
            "django.middleware.csrf.CsrfViewMiddleware",
        ):
            self.assertIn(guard, settings.MIDDLEWARE)

    def test_clean_receipt_and_child_read_neither_substitute_for_each_other(self):
        self.exact_range(self.staff, self.url, self.raw)
        del self.authority.grants[self.child_key]
        # A genuine current (synthetic-mode) receipt is still present, but it
        # cannot reveal even this exact child under only the case's READ grant.
        self.assertEqual(
            services.require(self.attachment["sha256"], len(self.raw))["mode"], "SYNTHETIC"
        )
        self.denied_file(self.staff.get(self.url), self.raw)
        self.child_key = self.allow(self.child, "CONFIDENTIAL", "READ")
        selected = self.scanner.current
        self.scanner.current = replace(selected, signature_version="SYNTHETIC-withdrawn")
        for method, options in (
            (self.staff.get, {}),
            (self.staff.head, {}),
            (self.staff.get, {"HTTP_RANGE": "bytes=4-19"}),
        ):
            self.denied_file(method(self.url, **options), self.raw)
        self.scanner.current = selected
        self.exact_range(self.staff, self.url, self.raw)
        self.assertEqual(self.originals(), self.before)

    def test_last_response_callback_can_revoke_privacy_or_scan_before_private_bytes_escape(self):
        actual = links._range_response
        selected = self.scanner.current

        def privacy_revoke(*args, **kwargs):
            response = actual(*args, **kwargs)
            self.authority.grants.pop(self.child_key, None)
            return response

        with patch.object(links, "_range_response", side_effect=privacy_revoke):
            self.denied_file(self.staff.get(self.url, HTTP_RANGE="bytes=4-19"), self.raw)
        self.child_key = self.allow(self.child, "CONFIDENTIAL", "READ")

        def scan_revoke(*args, **kwargs):
            response = actual(*args, **kwargs)
            self.scanner.current = replace(selected, signature_version="SYNTHETIC-late-withdrawn")
            return response

        with patch.object(links, "_range_response", side_effect=scan_revoke):
            self.denied_file(self.staff.get(self.url, HTTP_RANGE="bytes=4-19"), self.raw)
        self.scanner.current = selected
        self.exact_range(self.staff, self.url, self.raw)
        self.assertEqual(self.originals(), self.before)

    def test_actual_session_final_use_callback_cannot_release_old_privacy_or_scan_bytes(self):
        authority = NativeSessionAuthority(self.directory)
        selected = self.scanner.current
        with override_settings(
            FATWA_STAFF_SESSIONS_ENABLED=True,
            FATWA_STAFF_SESSION_AUTHORITY=authority,
            FATWA_STAFF_SESSION_RUNTIME_EPOCH="SYNTHETIC-upload-privacy-native-session-v1",
        ):
            # A real native login issues the server record and session-bound
            # cookie. The earlier legacy cookie is not reused or rewritten.
            self.staff = self.staff_for()
            self.assertEqual(Session.objects.count(), 1)
            self.url = self.attachment_url(self.staff, "staff")
            self.exact_range(self.staff, self.url, self.raw)
            actual = session_middleware._check
            for target in ("privacy", "scan"):
                calls = []

                def final_pass(lease, response):
                    # All inner domain/HTTP checks have returned an actual
                    # byte response before SessionContext performs its USE.
                    self.assertEqual(response.status_code, 206)
                    self.assertEqual(response.content, self.raw[4:20])
                    self.assertTrue(lease.bindings)
                    self.assertTrue(lease.final_guards)

                    def revoke(values):
                        self.assertEqual(values["action"], "USE")
                        calls.append(values["action"])
                        if target == "privacy":
                            self.authority.grants.pop(self.child_key, None)
                        else:
                            self.scanner.current = replace(
                                selected, signature_version="SYNTHETIC-final-session-withdrawn"
                            )

                    authority.hook = revoke
                    try:
                        return actual(lease, response)
                    finally:
                        authority.hook = None

                with self.subTest(target=target):
                    with patch.object(session_middleware, "_check", side_effect=final_pass):
                        self.denied_file(
                            self.staff.get(self.url, HTTP_RANGE="bytes=4-19"), self.raw
                        )
                    self.assertEqual(calls, ["USE"])
                    self.child_key = self.allow(self.child, "CONFIDENTIAL", "READ")
                    self.scanner.current = selected
                    self.exact_range(self.staff, self.url, self.raw)
        self.assertEqual(self.originals(), self.before)
