"""Independent native regressions for composed diagnostic authorization."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import media_boundary
from apps.casework.models import Case, CaseEvent
from apps.content_reports.authority import ContentReportAuthority
from apps.content_reports.tests import SETTINGS as REPORT_SETTINGS
from apps.content_reports.tests import FixtureAuthority, ReportFixture
from apps.source_rights.tests import ENABLED as RIGHTS_SETTINGS
from apps.source_rights.tests import Authority as SourceAuthority
from apps.source_rights.tests import RightsFixture
from apps.timed_citations.tests import SETTINGS as TIMED_SETTINGS
from apps.timed_citations.tests import Fixture as TimedFixture
from tests.casework.test_http import Directory, post

from . import views
from .tests import FEATURES, QualityFixture


class NativeFixture:
    credential = "synthetic-credential-with-32-characters"

    def setUp(self):
        super().setUp()
        configured = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        configured.enable()
        self.addCleanup(configured.disable)
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        login = self.client.get("/casework/staff/login/")
        authenticated = post(
            self.client, "/casework/staff/login/", {"credential": self.credential}, login
        )
        self.assertEqual(authenticated.status_code, 303)

    def page(self):
        response = self.client.get("/casework/staff/quality/")
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def check_state(self, response, code, state):
        self.assertContains(response, f'data-quality-check="{code}" data-quality-state="{state}"')

    def during_render(self, change):
        original = views.render

        def changed(*args, **kwargs):
            response = original(*args, **kwargs)
            change()
            return response

        with patch.object(views, "render", side_effect=changed):
            return self.client.get("/casework/staff/quality/")

    def assert_closed(self, response):
        self.assertEqual(response.status_code, 409, response.content)
        self.assertNotContains(response, "data-quality-check", status_code=409)


class UnversionedReports(ContentReportAuthority):
    def permits(self, **kwargs):
        # A permissive legacy callback cannot substitute for a usable version.
        return True


@override_settings(**{**REPORT_SETTINGS, **FEATURES, "FATWA_CONTENT_REPORTS_ENABLED": True})
class ReportBoundaryTests(NativeFixture, ReportFixture, TransactionTestCase):
    def pending(self):
        self.report(description="PRIVATE UNVERIFIED REPORT")
        page = self.page()
        self.assertContains(page, "توجد 1 بلاغات متاحة قيد المراجعة")
        self.assertNotContains(page, "PRIVATE UNVERIFIED REPORT")

    def test_report_feature_withdrawal_during_render_discards_prior_count(self):
        self.pending()
        before = list(Case.objects.values()), list(CaseEvent.objects.values())
        for withdrawn in (False, 1):
            with (
                self.subTest(withdrawn=withdrawn),
                patch.object(settings, "FATWA_CONTENT_REPORTS_ENABLED", True),
            ):
                response = self.during_render(
                    lambda: setattr(settings, "FATWA_CONTENT_REPORTS_ENABLED", withdrawn)
                )
                self.assert_closed(response)
        self.assertEqual(before, (list(Case.objects.values()), list(CaseEvent.objects.values())))

    def test_report_generation_revocation_after_render_discards_prior_count(self):
        self.pending()
        response = self.during_render(lambda: self.report_authority.denied.add("READ"))
        self.assert_closed(response)

    def test_report_authority_replacement_cannot_reuse_the_previous_generation(self):
        self.pending()
        replacement = FixtureAuthority(self.a["public_ref"])
        self.assertEqual(replacement.projection_epoch(), self.report_authority.projection_epoch())
        with patch.object(settings, "FATWA_CONTENT_REPORTS_AUTHORITY", self.report_authority):
            response = self.during_render(
                lambda: setattr(settings, "FATWA_CONTENT_REPORTS_AUTHORITY", replacement)
            )
        self.assert_closed(response)

    def test_optional_unavailable_report_policy_does_not_hide_other_diagnostics(self):
        self.pending()
        denied = FixtureAuthority(self.a["public_ref"])
        denied.denied.add("READ")
        for enabled, authority, expected in (
            (True, None, "NOT_CHECKED"),
            (True, UnversionedReports(), "NOT_CHECKED"),
            (True, denied, "NOT_CHECKED"),
            (False, UnversionedReports(), "NOT_APPLICABLE"),
        ):
            with (
                self.subTest(enabled=enabled, authority=type(authority).__name__),
                override_settings(
                    FATWA_CONTENT_REPORTS_ENABLED=enabled,
                    FATWA_CONTENT_REPORTS_AUTHORITY=authority,
                ),
            ):
                page = self.page()
                self.check_state(page, "reports", expected)
                self.check_state(page, "canonical", "OK")
                self.check_state(page, "attachments", "OK")
                self.assertNotContains(page, "توجد 1 بلاغات متاحة قيد المراجعة")
                self.assertNotContains(page, "PRIVATE UNVERIFIED REPORT")


@override_settings(**FEATURES)
class OriginalBoundaryTests(NativeFixture, QualityFixture, TransactionTestCase):
    credential = Directory.credential

    def test_original_storage_rebinding_and_reader_gate_withdrawal_close_the_page(self):
        self.storage()
        self.attach()
        self.check_state(self.page(), "attachments", "OK")
        for name, replacement in (
            ("FATWA_PRIVATE_MEDIA_STORAGE", None),
            ("FATWA_CASE_ATTACHMENTS_ENABLED", False),
        ):
            with self.subTest(setting=name), patch.object(settings, name, getattr(settings, name)):
                response = self.during_render(lambda: setattr(settings, name, replacement))
                self.assert_closed(response)
                self.assertNotIn(str(self.storage_root).encode(), response.content)


@override_settings(**{**RIGHTS_SETTINGS, **FEATURES, "FATWA_SOURCE_RIGHTS_ENFORCED": False})
class SourceBoundaryTests(NativeFixture, RightsFixture, TransactionTestCase):
    credential = "synthetic-editor-credential-32-characters"

    def test_reviewed_source_authority_withdrawal_and_rebinding_close_the_page(self):
        self.allow()
        with override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True):
            self.check_state(self.page(), "references", "OK")
            for replacement in (None, SourceAuthority(self.receipt["public_ref"])):
                with (
                    self.subTest(replacement=type(replacement).__name__),
                    patch.object(settings, "FATWA_SOURCE_RIGHTS_AUTHORITY", self.rights_authority),
                ):
                    response = self.during_render(
                        lambda: setattr(settings, "FATWA_SOURCE_RIGHTS_AUTHORITY", replacement)
                    )
                    self.assert_closed(response)


@override_settings(**{**TIMED_SETTINGS, **FEATURES})
class MediaBoundaryTests(NativeFixture, TimedFixture, TransactionTestCase):
    credential = "synthetic-editor-credential-32-characters"

    def setUp(self):
        super().setUp()
        self.annotation = self.propose()
        self.confirm(self.annotation)

    def test_valid_timed_policy_does_not_require_an_unused_toc_generation(self):
        self.assertEqual(self.opened(self.annotation)["raw"], self.audio["raw"])
        page = self.page()
        self.check_state(page, "answer_files", "OK")
        self.check_state(page, "references", "OK")
        self.assertNotContains(page, "PRIVATE synthetic human answer")
        self.assertNotContains(page, "PRIVATE exact human locator")

    def test_media_grant_revocation_during_render_still_discards_the_entire_page(self):
        self.check_state(self.page(), "references", "OK")
        response = self.during_render(lambda: self.rights.actions.remove("CITE"))
        self.assert_closed(response)

    def test_media_expiry_without_a_generation_change_still_closes_final_render(self):
        self.check_state(self.page(), "references", "OK")
        future = self.rights.valid_until + timedelta(seconds=1)
        clock = SimpleNamespace(now=timezone.now, is_naive=timezone.is_naive)
        with patch.object(media_boundary, "timezone", clock):
            response = self.during_render(lambda: setattr(clock, "now", lambda: future))
        self.assert_closed(response)
