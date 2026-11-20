"""Actual scoped diagnostics over required records, source rights and stored originals."""

import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.case_attachments.storage_bindings import reference
from apps.case_citations import services as citations
from apps.case_citations.tests import source_fixture
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent, CaseSource
from apps.content_reports.tests import SETTINGS as REPORT_SETTINGS
from apps.content_reports.tests import ReportFixture
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.private_media.filesystem import FileSystemStorage
from apps.reference.models import ReferenceHeading
from tests.casework.test_http import WEB_SETTINGS, Directory, hidden, post

from . import services, views

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_DATA_QUALITY_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_CASE_CITATIONS_ENABLED": True,
}


class QualityFixture:
    def setUp(self):
        super().setUp()
        self.directory = Directory()
        self.receipt = self.intake("one")
        self.directory.grant(self.receipt["public_ref"])
        configured = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        configured.enable()
        self.addCleanup(configured.disable)
        self.common = dict(
            subject_id=self.directory.current.subject_id,
            provider=self.directory,
            synthetic_fixtures_only=True,
        )

    def intake(self, key):
        return cases.intake_case(
            original_question="PRIVATE ORIGINAL " + key,
            source_event_id="quality-source-" + key,
            requester_id="quality-requester-" + key,
            idempotency_key="quality-request-" + key,
            synthetic_fixtures_only=True,
        )

    def inspect(self, **kwargs):
        return services.dashboard(**self.common, **kwargs)

    def case_common(self):
        return {**self.common, "case_id": self.receipt["case_id"]}

    def draft(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return cases.save_answer(
            **self.case_common(),
            text="PRIVATE ANSWER",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )

    def state(self, result, code):
        return next(c["state"] for c in result["rows"][0]["checks"] if c["code"] == code)

    def storage(self):
        temporary = tempfile.TemporaryDirectory(prefix="quality-originals-")
        self.addCleanup(temporary.cleanup)
        self.storage_root = Path(temporary.name) / "owned"
        self.storage_adapter = FileSystemStorage(self.storage_root, synthetic_fixtures_only=True)
        configured = override_settings(FATWA_PRIVATE_MEDIA_STORAGE=self.storage_adapter)
        configured.enable()
        self.addCleanup(configured.disable)

    def attach(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return attachments.upload(
            token=self.receipt["token"],
            raw=b"synthetic required original",
            filename="synthetic.txt",
            media_type="text/plain",
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )


@override_settings(**FEATURES)
class QualityTests(QualityFixture, TransactionTestCase):
    def test_no_optional_enrichment_is_not_a_defect_and_scan_writes_nothing(self):
        before = list(CaseEvent.objects.values()), list(Case.objects.values())
        result = self.inspect()
        self.assertEqual(result["technical_count"], 0)
        self.assertEqual(result["review_count"], 0)
        self.assertEqual(result["unchecked_count"], 0)
        self.assertNotIn("PRIVATE ORIGINAL", str(result))
        self.assertNotIn(self.receipt["token"], str(result))
        self.assertEqual(before, (list(CaseEvent.objects.values()), list(Case.objects.values())))
        self.draft()  # A successful diagnostic is not a prerequisite for editing.
        self.assertEqual(AnswerRevision.objects.count(), 1)

    def test_missing_required_source_is_detected_without_repairing_record(self):
        # The independent deferred SQL constraint prevents this malformed import
        # from committing. Diagnose it inside the same provisional unit without
        # disabling that constraint or fabricating a durable invalid database.
        with self.assertRaisesMessage(IntegrityError, "case source required"):
            with synthetic_queue_atomic():
                with patch.object(CaseSource.objects, "create", return_value=None):
                    broken = self.intake("missing-source")
                self.directory.grant(broken["public_ref"])
                result = self.inspect()
                self.assertEqual(self.state(result, "canonical"), "TECHNICAL")
                self.assertFalse(CaseSource.objects.filter(pk=broken["case_id"]).exists())
                self.assertEqual(CaseEvent.objects.filter(case_id=broken["case_id"]).count(), 1)
        self.assertFalse(Case.objects.filter(pk=broken["case_id"]).exists())

    def test_missing_required_physical_file_is_detected_and_refresh_recovers(self):
        self.storage()
        self.attach()
        row = CaseAttachment.objects.get(case_id=self.receipt["case_id"])
        path = self.storage_root / "objects" / row.storage_key
        raw = path.read_bytes()
        self.assertEqual(self.state(self.inspect(), "attachments"), "OK")
        path.unlink()
        result = self.inspect()
        self.assertEqual(self.state(result, "attachments"), "TECHNICAL")
        self.assertNotIn(row.storage_key, str(result))
        self.assertNotIn(str(self.storage_root), str(result))
        self.assertEqual(CaseAttachment.objects.count(), 1)
        # Synthetic operator restore uses the real integrity-checked storage
        # adapter; the dashboard itself never writes or repairs any content.
        self.storage_adapter.restore(reference(row), raw)
        self.assertEqual(self.state(self.inspect(), "attachments"), "OK")

    def test_changed_answer_original_bytes_detected_without_changing_approval(self):
        self.storage()
        result = media.save_multipart_answer(
            **self.case_common(),
            text="PRIVATE AUDIO ANSWER",
            files=[audio_fixture()],
            expected_revision=1,
            expected_evidence_version=1,
        )
        cases.record_decision(
            **self.case_common(),
            answer_id=result["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        row = AnswerPart.objects.get(ordinal=2)
        before = list(Case.objects.values()), list(CaseEvent.objects.values())
        path = self.storage_root / "objects" / row.storage_key
        path.unlink()
        path.write_bytes(b"tampered synthetic file")
        path.chmod(0o400)
        self.assertEqual(self.state(self.inspect(), "answer_files"), "TECHNICAL")
        self.assertEqual(before, (list(Case.objects.values()), list(CaseEvent.objects.values())))

    def test_mismatched_author_and_saved_event_is_a_technical_defect(self):
        original = AnswerRevision.objects.create

        def wrong_author(**kwargs):
            return original(**{**kwargs, "subject_id": "different-author"})

        with patch.object(AnswerRevision.objects, "create", side_effect=wrong_author):
            self.draft()
        result = self.inspect()
        self.assertEqual(self.state(result, "attribution"), "TECHNICAL")
        self.assertNotIn("different-author", str(result))

    def test_exact_reference_and_withdrawn_right_are_distinguished(self):
        edition = source_fixture()
        source = citations.read_source(**self.case_common(), edition_id=edition, source_row_id=2)
        citations.save_cited_answer(
            **self.case_common(),
            text="PRIVATE CITED ANSWER",
            selections=[
                dict(
                    edition_id=edition,
                    source_row_id=2,
                    source_sha256=source["source_sha256"],
                    editorial_note="PRIVATE SOURCE NOTE",
                )
            ],
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.assertEqual(self.state(self.inspect(), "references"), "OK")
        # The real strict ledger has no reviewed READ/CITE grants in this case.
        with override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True, FATWA_SOURCE_RIGHTS_ENABLED=True):
            result = self.inspect()
        self.assertEqual(self.state(result, "references"), "NOT_CHECKED")
        self.assertEqual(result["technical_count"], 0)
        self.assertNotIn(source["source"]["heading_title"], str(result))
        self.assertNotIn("PRIVATE SOURCE NOTE", str(result))

    def test_out_of_scope_cases_never_enter_diagnostic_readers_or_counts(self):
        foreign = self.intake("foreign")
        result = self.inspect()
        self.assertEqual(result["page_case_count"], 1)
        self.assertNotIn(foreign["public_ref"], str(result))
        with self.assertRaises(cases.CaseConflict):
            self.inspect(case_ref=foreign["public_ref"])

    def test_source_catalog_repoint_is_rejected_and_diagnostic_keeps_exact_original(self):
        edition = source_fixture()
        source = citations.read_source(**self.case_common(), edition_id=edition, source_row_id=2)
        citations.save_cited_answer(
            **self.case_common(),
            text="PRIVATE CITED ANSWER",
            selections=[
                {
                    "edition_id": edition,
                    "source_row_id": 2,
                    "source_sha256": source["source_sha256"],
                    "editorial_note": "PRIVATE SAVED SOURCE NOTE",
                }
            ],
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.assertEqual(self.state(self.inspect(), "references"), "OK")
        before = list(Case.objects.values()), list(CaseEvent.objects.values())
        # The source store independently prevents committed catalog corruption;
        # diagnostics must not weaken that guard to manufacture a broken source.
        with self.assertRaisesMessage(IntegrityError, "Source catalog snapshots are immutable"):
            with transaction.atomic():
                ReferenceHeading.objects.filter(edition_id=edition, source_row_id=2).update(
                    title_original="CHANGED SYNTHETIC REFERENCE"
                )
        result = self.inspect()
        self.assertEqual(self.state(result, "references"), "OK")
        self.assertNotIn("CHANGED SYNTHETIC REFERENCE", str(result))
        self.assertNotIn("PRIVATE SAVED SOURCE NOTE", str(result))
        self.assertEqual(before, (list(Case.objects.values()), list(CaseEvent.objects.values())))

    def test_final_batch_scope_and_provider_recheck_discards_previous_rows(self):
        another = self.intake("another")
        self.directory.grant(self.receipt["public_ref"], another["public_ref"])
        ordered = list(Case.objects.order_by("id").values_list("public_ref", flat=True))
        original = services._inspect_case

        def inspect(case, actor, common, report_policy):
            value = original(case, actor, common, report_policy)
            if case.public_ref == ordered[-1]:
                self.directory.grant(ordered[-1])
            return value

        with (
            patch.object(services, "_inspect_case", side_effect=inspect),
            self.assertRaisesMessage(cases.CaseConflict, "quality_identity_changed"),
        ):
            self.inspect()

    def test_expiry_refresh_is_allowed_but_revoked_role_and_closed_flag_deny(self):
        original = self.directory.resolve

        def refreshed(subject):
            from datetime import timedelta

            return replace(original(subject), valid_until=timezone.now() + timedelta(minutes=25))

        with patch.object(self.directory, "resolve", side_effect=refreshed):
            self.assertEqual(self.inspect()["page_case_count"], 1)
        self.directory.current = replace(self.directory.current, role="ORGANIZER_ADMIN")
        with self.assertRaises(cases.CaseConflict):
            self.inspect()
        with (
            override_settings(FATWA_DATA_QUALITY_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.inspect()

    def test_bounded_pages_do_not_hide_remaining_cases_or_mutate_state(self):
        receipts = [self.receipt, *[self.intake("page-" + str(i)) for i in range(9)]]
        self.directory.grant(*(row["public_ref"] for row in receipts))
        first, second = self.inspect(), self.inspect(page=2)
        self.assertEqual((first["page_case_count"], second["page_case_count"]), (8, 2))
        self.assertEqual((first["next_page"], second["previous_page"]), (2, 1))
        self.assertEqual(len({r["public_ref"] for r in first["rows"] + second["rows"]}), 10)
        with self.assertRaises(cases.CaseConflict):
            self.inspect(page=0)


@override_settings(**FEATURES)
class QualityHTTPTests(QualityFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        login = self.client.get("/casework/staff/login/")
        self.assertEqual(
            post(
                self.client,
                "/casework/staff/login/",
                {"credential": self.directory.credential},
                login,
            ).status_code,
            303,
        )

    def test_native_page_refresh_case_selection_and_private_headers(self):
        page = self.client.get("/casework/staff/quality/")
        self.assertEqual(page.status_code, 200, page.content)
        self.assertIn("no-store", page["Cache-Control"])
        self.assertIn("noindex", page["X-Robots-Tag"])
        self.assertNotContains(page, "PRIVATE ORIGINAL")
        self.assertContains(page, "غياب التفريغ الاختياري")
        current = post(
            self.client,
            "/casework/staff/",
            {"action": "quality_case", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(current.status_code, 200, current.content)
        self.assertContains(current, self.receipt["public_ref"])
        refreshed = post(
            self.client, "/casework/staff/", {"action": "quality_open", "page": "1"}, current
        )
        self.assertEqual(refreshed.status_code, 200)

    def test_native_csrf_exact_fields_and_untrusted_selection_are_denied(self):
        page = self.client.get("/casework/staff/quality/")
        self.assertEqual(
            self.client.post(
                "/casework/staff/", {"action": "quality_open", "page": "1"}
            ).status_code,
            403,
        )
        self.assertEqual(
            post(
                self.client,
                "/casework/staff/",
                {"action": "quality_open", "page": "1", "repair": "yes"},
                page,
            ).status_code,
            400,
        )
        raw = "action=quality_open&page=1&page=2&csrfmiddlewaretoken=" + hidden(
            page, "csrfmiddlewaretoken"
        )
        self.assertEqual(
            self.client.post(
                "/casework/staff/", raw, content_type="application/x-www-form-urlencoded"
            ).status_code,
            400,
        )
        self.assertEqual(self.client.get("/casework/staff/quality/?scope=all").status_code, 400)

    def test_role_revocation_during_render_discards_entire_response(self):
        original = views.render

        def revoked(*args, **kwargs):
            result = original(*args, **kwargs)
            self.directory.current = replace(self.directory.current, active=False)
            return result

        with patch.object(views, "render", side_effect=revoked):
            page = self.client.get("/casework/staff/quality/")
        self.assertEqual(page.status_code, 409)
        self.assertNotIn(self.receipt["public_ref"].encode(), page.content)


@override_settings(**{**REPORT_SETTINGS, **FEATURES, "FATWA_CONTENT_REPORTS_ENABLED": True})
class QualityReportTests(ReportFixture, TransactionTestCase):
    def test_unverified_report_is_human_review_not_a_technical_or_scholarly_verdict(self):
        submitted = self.report(description="PRIVATE UNVERIFIED ALLEGATION")
        before = list(Case.objects.values()), list(CaseEvent.objects.values())
        common = {key: value for key, value in self.staff().items() if key != "case_id"}
        result = services.dashboard(**common, case_ref=self.a["public_ref"])
        check = next(c for c in result["rows"][0]["checks"] if c["code"] == "reports")
        self.assertEqual(check["state"], "REVIEW")
        self.assertEqual(result["technical_count"], 0)
        self.assertNotIn("PRIVATE UNVERIFIED ALLEGATION", str(result))
        started = self.advance(submitted, "START")
        self.advance(started, "RESOLVE", verification_note="تحقق بشري من المادة الاصطناعية")
        result = services.dashboard(**common, case_ref=self.a["public_ref"])
        self.assertEqual(result["review_count"], 0)
        self.assertEqual(before, (list(Case.objects.values()), list(CaseEvent.objects.values())))
