"""Actual native forms and signed downloads with the campaign middleware intact."""

import io
import json
import re
from dataclasses import replace
from html import unescape
from unittest.mock import patch
from urllib.parse import urlencode

from django.core.management import call_command
from django.test import Client, TransactionTestCase, override_settings

from apps.private_media.test_signed_links import LINK_SETTINGS
from apps.staff_sessions import middleware as session_middleware
from apps.staff_sessions.authority import ReauthenticationRule, SessionAuthority
from apps.staff_sessions.models import Session, SessionRevocation
from config.settings import campaign_review
from tests.casework.test_http import post

from .models import DerivativeJob, DerivedOutput
from .test_support import FEATURES, DerivativeFixture
from .views import BASE

NATIVE = {**FEATURES, **LINK_SETTINGS}


def forms(response):
    for text in re.findall(r"<form\b.*?</form>", response.content.decode(), re.S):
        values = {}
        for name, value in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', text):
            values[unescape(name)] = unescape(value)
        yield values


def submit(client, values):
    return client.post(BASE, urlencode(values), content_type="application/x-www-form-urlencoded")


class SessionPolicy(SessionAuthority):
    def __init__(self, directory):
        actor = directory.resolve("editor")
        self.claims = {
            "provider_id": directory.provider_id,
            "subject_id": actor.subject_id,
            "role": actor.role,
            "auth_epoch": actor.auth_epoch,
        }
        self.hook = None
        self.denied = set()

    def projection_epoch(self):
        return repr((self.claims, sorted(self.denied)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            all(values[key] == value for key, value in self.claims.items())
            and values["action"] in {"ISSUE", "USE", "LOGOUT"}
            and values["action"] not in self.denied
            and values["resource"]["surface"] == "CASEWORK"
            and values["resource"]["subject_id"] == self.claims["subject_id"]
            and values["resource"]["provider_id"] == self.claims["provider_id"]
        )

    def reauthentication(self, **values):
        return ReauthenticationRule(True, 90)


class NativeFixture(DerivativeFixture):
    def login(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        result = post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            page,
        )
        self.assertEqual(result.status_code, 303, result.content)
        return client

    def open(self, client):
        page = client.get(BASE)
        self.assertEqual(page.status_code, 200, page.content)
        selected = next(
            form for form in forms(page) if form.get("case_ref") == self.receipt["public_ref"]
        )
        result = submit(client, selected)
        self.assertEqual(result.status_code, 200, result.content)
        return result

    def enqueue(self, client):
        page = self.open(client)
        selected = next(
            form
            for form in forms(page)
            if form.get("action") == "media_jobs_prepare"
            and form.get("source") == "ATTACHMENT:" + self.attachment["id"]
        )
        result = submit(client, selected)
        self.assertEqual(result.status_code, 200, result.content)
        return DerivativeJob.objects.latest("created_at"), result

    def output_url(self, page, job):
        urls = [
            unescape(url) for url in re.findall(r'(?:src|href)="([^"]+)"', page.content.decode())
        ]
        return next(url for url in urls if url.startswith(BASE + str(job.pk) + "/output/?access="))

    def execute_command(self, job):
        result = io.StringIO()
        with override_settings(FATWA_MEDIA_DERIVATIVES_WORKER_DIRECTORY=self.directory):
            call_command(
                "process_media_derivative",
                job=str(job.pk),
                synthetic_fixtures_only=True,
                stdout=result,
            )
        return json.loads(result.getvalue())["jobs"][0]

    def denied_file(self, response):
        self.assertEqual(response.status_code, 404, response.content)
        self.assertNotIn(self.raw, response.content)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        for key in ("ETag", "Content-Range", "Content-Disposition", "X-Content-SHA256"):
            self.assertNotIn(key, response)


@override_settings(**NATIVE)
class NativeDerivativeTests(NativeFixture, TransactionTestCase):
    def test_native_queue_unavailable_retry_original_signed_output_and_download(self):
        client = self.login()
        with override_settings(FATWA_MEDIA_DERIVATIVES_PROCESSOR=None):
            job, page = self.enqueue(client)
            self.assertIn(b'data-job-state="QUEUED"', page.content)
            self.assertFalse(DerivedOutput.objects.exists())
            self.assertEqual(self.execute_command(job)["state"], "UNAVAILABLE")
        page = self.open(client)
        self.assertIn(b'data-job-state="UNAVAILABLE"', page.content)
        original = next(
            unescape(url)
            for url in re.findall(r'href="([^"]+)"', page.content.decode())
            if "/attachments/" in url
        )
        self.assertEqual(client.get(original).content, self.raw)
        retry = next(form for form in forms(page) if form.get("action") == "media_jobs_retry")
        self.assertEqual(submit(client, retry).status_code, 200)
        self.assertEqual(self.execute_command(job)["state"], "READY")
        page = self.open(client)
        url = self.output_url(page, job)
        self.assertEqual(client.get(url).content, self.raw)
        partial = client.get(url, HTTP_RANGE="bytes=4-19")
        self.assertEqual((partial.status_code, partial.content), (206, self.raw[4:20]))
        self.assertEqual(client.head(url).content, b"")
        download = next(form for form in forms(page) if form.get("action") == "media_jobs_download")
        copied = submit(client, download)
        self.assertEqual(copied.content, self.raw)
        self.assertTrue(copied["Content-Disposition"].startswith("attachment;"))
        self.assertIn("التفريغ الآلي غير متاح", page.content.decode())

    def test_ticket_never_replaces_source_right_or_scan_on_get_head_range(self):
        client = self.login()
        job, _ = self.enqueue(client)
        self.assertEqual(self.execute_command(job)["state"], "READY")
        url = self.output_url(self.open(client), job)
        self.denied_file(client.get(url.split("?")[0]))
        self.rights.denied.add(("ATTACHMENT", "READ_MEDIA"))
        for method, args in (
            (client.get, {}),
            (client.head, {}),
            (client.get, {"HTTP_RANGE": "bytes=4-19"}),
        ):
            self.denied_file(method(url, **args))
        self.rights.denied.clear()
        selected = self.scanner.current
        self.scanner.current = replace(selected, signature_version="SYNTHETIC-old-ticket-revoked")
        self.denied_file(client.get(url))
        self.scanner.current = selected
        self.assertEqual(client.get(url).content, self.raw)

    def test_native_csrf_duplicate_unknown_fields_foreign_session_and_remote_are_closed(self):
        client = self.login()
        page = self.open(client)
        form = next(form for form in forms(page) if form.get("action") == "media_jobs_prepare")
        missing_csrf = {key: value for key, value in form.items() if key != "csrfmiddlewaretoken"}
        self.assertEqual(submit(client, missing_csrf).status_code, 403)
        self.assertEqual(submit(client, {**form, "provider": "invented"}).status_code, 400)
        duplicate = client.post(
            BASE,
            urlencode(form) + "&task=AUDIO_PLAYBACK",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(duplicate.status_code, 400)
        anonymous = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.assertEqual(anonymous.get(BASE).status_code, 404)
        self.assertEqual(client.get(BASE, REMOTE_ADDR="203.0.113.4").status_code, 403)
        self.assertEqual(DerivativeJob.objects.count(), 0)

    def test_actual_session_final_use_cannot_release_output_after_source_or_scan_revocation(self):
        session_policy = SessionPolicy(self.directory)
        with override_settings(
            FATWA_STAFF_SESSIONS_ENABLED=True,
            FATWA_STAFF_SESSION_AUTHORITY=session_policy,
            FATWA_STAFF_SESSION_RUNTIME_EPOCH="SYNTHETIC-media-derivative-session-runtime-v1",
        ):
            client = self.login()
            self.assertEqual(Session.objects.count(), 1)
            job, _ = self.enqueue(client)
            self.assertIsNotNone(job.origin_session_id)
            self.assertEqual(self.execute_command(job)["state"], "READY")
            url = self.output_url(self.open(client), job)
            self.assertEqual(client.get(url).content, self.raw)
            actual = session_middleware._check
            selected = self.scanner.current
            for target in ("source", "scan"):
                calls = []

                def final(lease, response):
                    self.assertEqual(
                        (response.status_code, response.content), (206, self.raw[4:20])
                    )
                    self.assertTrue(lease.final_guards)

                    def revoke(values):
                        if values["action"] == "USE":
                            calls.append(target)
                            if target == "source":
                                self.rights.denied.add(("ATTACHMENT", "READ_MEDIA"))
                            else:
                                self.scanner.current = replace(
                                    selected, signature_version="SYNTHETIC-session-last-scan"
                                )

                    session_policy.hook = revoke
                    try:
                        return actual(lease, response)
                    finally:
                        session_policy.hook = None

                with patch.object(session_middleware, "_check", side_effect=final):
                    self.denied_file(client.get(url, HTTP_RANGE="bytes=4-19"))
                self.assertTrue(calls)
                self.rights.denied.clear()
                self.scanner.current = selected
                self.assertEqual(client.get(url).content, self.raw)
            self.assertEqual(
                campaign_review.MIDDLEWARE[0], "apps.platform_recovery.middleware.MaintenanceGuard"
            )
            from django.conf import settings

            self.assertTrue(set(campaign_review.MIDDLEWARE).issubset(settings.MIDDLEWARE))
            self.assertLess(
                settings.MIDDLEWARE.index("apps.staff_sessions.middleware.SessionContext"),
                settings.MIDDLEWARE.index("apps.media_derivatives.policy.DerivativeResponses"),
            )

    def test_logged_out_origin_is_only_a_veto_and_cannot_be_reused_by_worker(self):
        session_policy = SessionPolicy(self.directory)
        with override_settings(
            FATWA_STAFF_SESSIONS_ENABLED=True,
            FATWA_STAFF_SESSION_AUTHORITY=session_policy,
            FATWA_STAFF_SESSION_RUNTIME_EPOCH="SYNTHETIC-media-derivative-session-runtime-v1",
        ):
            client = self.login()
            job, page = self.enqueue(client)
            # Native self-logout writes the immutable revocation record.
            token = client.cookies["fatwa_casework_csrf"].value
            logged_out = client.post(
                "/casework/staff/logout/",
                urlencode({"csrfmiddlewaretoken": token}),
                content_type="application/x-www-form-urlencoded",
            )
            self.assertEqual(logged_out.status_code, 303, logged_out.content)
            self.assertEqual(SessionRevocation.objects.count(), 1)
            self.assertEqual(self.execute_command(job)["state"], "NOT_EXECUTED")
            self.assertEqual(DerivedOutput.objects.count(), 0)

    def test_actual_session_final_callback_rechecks_classified_source_before_bytes(self):
        import uuid
        from datetime import timedelta

        from django.utils import timezone

        from apps.data_privacy import services as privacy
        from apps.data_privacy import test_support as fixtures
        from apps.data_privacy.authority import Grant
        from apps.data_privacy.catalog import locate

        session_policy = SessionPolicy(self.directory)
        authority = fixtures.Authority()
        with override_settings(
            FATWA_STAFF_SESSIONS_ENABLED=True,
            FATWA_STAFF_SESSION_AUTHORITY=session_policy,
            FATWA_STAFF_SESSION_RUNTIME_EPOCH="SYNTHETIC-media-derivative-privacy-session-v1",
        ):
            client = self.login()
            job, _ = self.enqueue(client)
            self.assertEqual(self.execute_command(job)["state"], "READY")
            with override_settings(
                FATWA_DATA_PRIVACY_ENABLED=True, FATWA_DATA_PRIVACY_AUTHORITY=authority
            ):
                principal = privacy.staff_principal(
                    self.directory, self.directory.resolve("editor")
                )
                child_key = None
                for kind, identifier in (
                    ("CASE", self.receipt["case_id"]),
                    ("ATTACHMENT", self.attachment["id"]),
                ):
                    target = locate(kind, identifier)
                    values = dict(
                        audience=principal.audience,
                        provider_id=principal.provider_id,
                        subject_id=principal.subject_id,
                        auth_epoch=principal.auth_epoch,
                        role=principal.role,
                        case_ref=target.case_ref,
                        target_kind=kind,
                        target_id=target.identifier,
                        source_digest=target.source_digest,
                        classification="CONFIDENTIAL",
                        previous_level="",
                    )
                    authority.grants[authority.key({**values, "action": "CLASSIFY"})] = Grant(
                        timezone.now() + timedelta(minutes=10)
                    )
                    privacy.classify(
                        kind=kind,
                        identifier=identifier,
                        level="CONFIDENTIAL",
                        note="تصنيف مصدر اصطناعي محفوظ",
                        expected_digest=privacy.ZERO,
                        expected_source_digest=target.source_digest,
                        request_key=uuid.uuid4(),
                        provider=self.directory,
                        subject_id="editor",
                        synthetic_fixtures_only=True,
                    )
                    key = authority.key({**values, "action": "READ"})
                    authority.grants[key] = Grant(timezone.now() + timedelta(minutes=10))
                    if kind == "ATTACHMENT":
                        child_key = key
                url = self.output_url(self.open(client), job)
                self.assertEqual(client.get(url).content, self.raw)
                actual = session_middleware._check
                calls = []

                def final(lease, response):
                    self.assertEqual(
                        (response.status_code, response.content), (206, self.raw[4:20])
                    )
                    self.assertTrue(lease.final_guards)

                    def revoke(values):
                        if values["action"] == "USE":
                            calls.append(True)
                            authority.grants.pop(child_key, None)

                    session_policy.hook = revoke
                    try:
                        return actual(lease, response)
                    finally:
                        session_policy.hook = None

                with patch.object(session_middleware, "_check", side_effect=final):
                    self.denied_file(client.get(url, HTTP_RANGE="bytes=4-19"))
                self.assertTrue(calls)
                authority.grants[child_key] = Grant(timezone.now() + timedelta(minutes=10))
                self.assertEqual(client.get(url).content, self.raw)
