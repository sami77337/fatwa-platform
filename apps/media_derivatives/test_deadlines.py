"""An explicit derivative grant expires independently of its actor and later grants."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.staff_sessions import middleware as session_middleware

from . import services
from . import test_http as native
from .test_support import Authority


class FiniteAuthority(Authority):
    def __init__(self, ref):
        super().__init__(ref)
        self.until = timezone.now() + timedelta(minutes=10)
        self.short_read = None

    def projection_epoch(self):
        return repr((super().projection_epoch(), self.until, self.short_read))

    def grant_deadline(self, **values):
        return self.short_read if self.short_read and values["action"] == "READ" else self.until

    def permits(self, **values):
        return super().permits(**values) and timezone.now() < self.grant_deadline(**values)


@override_settings(**native.NATIVE)
class DerivativeGrantDeadlineTests(native.NativeFixture, TransactionTestCase):
    def test_final_real_session_use_cannot_extend_short_read_with_longer_download_grant(self):
        authority = FiniteAuthority(self.receipt["public_ref"])
        session_policy = native.SessionPolicy(self.directory)
        with override_settings(
            FATWA_MEDIA_DERIVATIVES_AUTHORITY=authority,
            FATWA_STAFF_SESSIONS_ENABLED=True,
            FATWA_STAFF_SESSION_AUTHORITY=session_policy,
            FATWA_STAFF_SESSION_RUNTIME_EPOCH="SYNTHETIC-derivative-grant-expiry-v1",
        ):
            client = self.login()
            job, _ = self.enqueue(client)
            self.assertEqual(self.execute_command(job)["state"], "READY")
            page = self.open(client)
            url = self.output_url(page, job)
            download = next(
                form for form in native.forms(page) if form.get("action") == "media_jobs_download"
            )
            now = timezone.now()
            authority.short_read = now + timedelta(seconds=1)
            # DOWNLOAD and all identity/session grants stay valid for minutes.
            # The pure policy epoch contains the deadline but does not change
            # merely because time advances; this is an independent expiry check.
            initial_epoch = authority.projection_epoch()
            actual = session_middleware._check
            for name, operation, status, expected in (
                (
                    "signed-range",
                    lambda: client.get(url, HTTP_RANGE="bytes=4-19"),
                    206,
                    self.raw[4:20],
                ),
                ("explicit-download", lambda: native.submit(client, download), 200, self.raw),
            ):
                with self.subTest(name=name):
                    final_calls = []

                    def final(lease, response):
                        self.assertEqual(
                            (response.status_code, response.content), (status, expected)
                        )
                        self.assertTrue(lease.final_guards)

                        def expire(values):
                            if values["action"] == "USE":
                                final_calls.append(True)

                        session_policy.hook = expire
                        try:
                            return actual(lease, response)
                        finally:
                            session_policy.hook = None

                    with (
                        patch(
                            "apps.media_derivatives.policy.timezone.now",
                            side_effect=lambda: now + timedelta(seconds=2) if final_calls else now,
                        ),
                        patch.object(session_middleware, "_check", side_effect=final),
                    ):
                        response = operation()
                        self.assertEqual(response.status_code, 404)
                        self.denied_file(response)
                    self.assertTrue(final_calls)
                    self.assertEqual(authority.projection_epoch(), initial_epoch)

    def test_missing_naive_expired_or_unbounded_grant_deadline_is_not_an_identity_fallback(self):
        job = self.execute(self.prepare())
        now = timezone.now()
        for value in (
            None,
            False,
            "long-lived",
            now.replace(tzinfo=None) + timedelta(seconds=30),
            now - timedelta(microseconds=1),
            now + timedelta(hours=2),
        ):
            with self.subTest(value=repr(value)):
                with patch.object(
                    self.authority, "grant_deadline", return_value=value, create=True
                ):
                    with self.assertRaises(cases.CaseConflict):
                        services.read_output(**self.common, job_id=job["id"])
        with patch.object(self.authority, "grant_deadline", None, create=True):
            with self.assertRaises(cases.CaseConflict):
                services.read_output(**self.common, job_id=job["id"])
        self.assertEqual(services.read_output(**self.common, job_id=job["id"])["raw"], self.raw)
