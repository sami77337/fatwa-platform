"""Independent final-boundary regressions from the integration review."""

from unittest.mock import patch

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.experimental_publication import services as publication
from apps.research_workspace.tests import SETTINGS as RESEARCH_SETTINGS
from apps.research_workspace.tests import ResearchFixture
from tests.casework.test_http import post

from . import services, views
from . import tests as fixtures
from .models import ContentReport, ReportEvent
from .tests import FixtureAuthority, VersionedKnowledgeAuthority


@override_settings(
    **{
        **RESEARCH_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_CONTENT_REPORTS_ENABLED": True,
    }
)
class ReportPolicyBoundaryTests(ResearchFixture, TransactionTestCase):
    prepared = fixtures.StaffSourceReportTests.prepared
    submit = fixtures.StaffSourceReportTests.submit

    def setUp(self):
        super().setUp()
        self.reporting_authority = FixtureAuthority(
            self.receipt["public_ref"], "synthetic-publication-directory", "editor"
        )
        self.authority = VersionedKnowledgeAuthority(self.receipt["public_ref"])
        configured = override_settings(
            FATWA_CONTENT_REPORTS_AUTHORITY=self.reporting_authority,
            FATWA_KNOWLEDGE_LINKS_AUTHORITY=self.authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def _change_on_final_submit_grant(self, change):
        original = self.reporting_authority.permits
        calls = 0

        def permits(**kwargs):
            nonlocal calls
            if kwargs["action"] == "SUBMIT":
                calls += 1
                if calls == 2:
                    change()
            return original(**kwargs)

        return patch.object(self.reporting_authority, "permits", side_effect=permits)

    def test_mixed_kind_last_permission_callback_cannot_keep_prior_allowed_rows(self):
        for kind in ("PUBLICATION", "TRANSCRIPT"):
            self.submit(self.prepared(kind))
        original = self.reporting_authority.permits
        denied, calls = set(), []

        def permits(**kwargs):
            if kwargs["action"] == "READ":
                calls.append(kwargs["target_kind"])
                if len(calls) == 4:
                    denied.add(({"PUBLICATION", "TRANSCRIPT"} - {kwargs["target_kind"]}).pop())
            return kwargs["target_kind"] not in denied and original(**kwargs)

        epoch = self.reporting_authority.projection_epoch
        with (
            patch.object(self.reporting_authority, "permits", side_effect=permits),
            patch.object(
                self.reporting_authority,
                "projection_epoch",
                side_effect=lambda: repr((epoch(), sorted(denied))),
            ),
            self.assertRaisesRegex(cases.CaseConflict, "report_policy_changed"),
        ):
            services.staff_desk(**self.common)
        self.assertEqual(len(denied), 1)

    def test_final_reporting_grant_cannot_revoke_transcript_policy_after_last_source_read(self):
        selected = self.prepared("TRANSCRIPT")
        with (
            self._change_on_final_submit_grant(
                lambda: self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
            ),
            self.assertRaisesRegex(cases.CaseConflict, "source_policy_changed"),
        ):
            self.submit(selected)
        self.assertEqual((ContentReport.objects.count(), ReportEvent.objects.count()), (0, 0))

    def test_final_reporting_grant_cannot_revoke_separate_transcript_open_permission(self):
        selected = self.prepared("TRANSCRIPT")
        with (
            self._change_on_final_submit_grant(
                lambda: setattr(self.authority, "allow_open", False)
            ),
            self.assertRaisesRegex(cases.CaseConflict, "source_policy_changed"),
        ):
            self.submit(selected)
        self.assertEqual(ContentReport.objects.count(), 0)

    def test_final_reporting_grant_cannot_withdraw_publication_after_last_source_read(self):
        selected = self.prepared()

        def withdraw():
            publication.act(
                **{**self.common, "subject_id": "publisher"},
                edition_id=self.edition["id"],
                action="WITHDRAW",
            )

        with (
            self._change_on_final_submit_grant(withdraw),
            self.assertRaisesRegex(cases.CaseConflict, "source_policy_changed"),
        ):
            self.submit(selected)
        self.assertEqual(ContentReport.objects.count(), 0)
        # The nested callback's write is rolled back with the refused report.
        self.assertEqual(
            publication.library(
                subject_id="editor", provider=self.directory, synthetic_fixtures_only=True
            )[0]["id"],
            self.edition["id"],
        )

    def test_unversioned_reporting_or_transcript_policy_fails_before_projection(self):
        with patch.object(self.reporting_authority, "projection_epoch", return_value=None):
            with self.assertRaisesRegex(cases.CaseConflict, "snapshot_required"):
                services.staff_desk(**self.common)
        with patch.object(self.authority, "projection_epoch", return_value=None):
            with self.assertRaisesRegex(cases.CaseConflict, "snapshot_required"):
                self.prepared("TRANSCRIPT")

    def _client(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        login = client.get("/casework/staff/login/")
        response = post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            login,
        )
        self.assertEqual(response.status_code, 303)
        return client, client.get("/casework/staff/")

    def test_authority_change_during_staff_render_cannot_expose_report_notes(self):
        self.submit(self.prepared(), description="SECRET REPORT NOTE")
        client, page = self._client()
        original = views.render

        def revoked(*args, **kwargs):
            response = original(*args, **kwargs)
            settings.FATWA_CONTENT_REPORTS_AUTHORITY.denied.add("READ")
            return response

        with patch.object(views, "render", side_effect=revoked):
            result = post(
                client,
                "/casework/staff/",
                {
                    "action": "reports_open",
                    "case_ref": self.receipt["public_ref"],
                },
                page,
            )
        self.assertEqual(result.status_code, 409)
        self.assertNotIn(b"SECRET REPORT NOTE", result.content)

    def test_transcript_policy_change_during_prepare_render_denies_the_whole_response(self):
        client, page = self._client()
        original = views.render

        def revoked(*args, **kwargs):
            response = original(*args, **kwargs)
            self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
            return response

        with patch.object(views, "render", side_effect=revoked):
            result = post(
                client,
                "/casework/staff/",
                {
                    "action": "report_prepare",
                    "case_ref": self.receipt["public_ref"],
                    "target_kind": "TRANSCRIPT",
                    "target_id": self.transcript["link_id"],
                },
                page,
            )
        self.assertEqual(result.status_code, 409)
        self.assertNotIn(self.transcript["link_id"].encode(), result.content)
