"""Real PostgreSQL persistence and HTTP file transfer using fabricated UTF-8 files."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseEvidence
from tests.casework.test_core import TestDirectory
from tests.casework.test_http import Directory, hidden, post

from . import services
from .models import CaseAttachment

RAW = "نص مرفق اصطناعي\r\n<script>not executable</script>\n".encode()


def new_case():
    key = secrets.token_hex(12)
    return cases.intake_case(
        original_question="سؤال اصطناعي",
        source_event_id=key,
        requester_id="rq-" + key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )


def staff_common(receipt, provider=None):
    return dict(
        case_id=receipt["case_id"],
        subject_id="synthetic-mufti",
        provider=provider or TestDirectory([receipt["public_ref"]]),
        synthetic_fixtures_only=True,
    )


def upload(receipt, **changes):
    args = dict(
        token=receipt["token"],
        raw=RAW,
        filename="synthetic.txt",
        media_type="text/plain",
        expected_revision=receipt["revision"],
        synthetic_fixtures_only=True,
    )
    args.update(changes)
    return services.upload(**args)


@override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=True)
class AttachmentTests(TransactionTestCase):
    def test_original_persists_and_exact_new_evidence_invalidates_approval(self):
        receipt = new_case()
        draft = cases.save_answer(
            **staff_common(receipt),
            text="تحرير بشري اصطناعي",
            expected_revision=1,
            expected_evidence_version=1,
        )
        approved = cases.record_decision(
            **staff_common(receipt),
            answer_id=draft["answers"][0]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        result = upload(receipt, expected_revision=approved["revision"])
        connections.close_all()
        row = CaseAttachment.objects.get()
        self.assertEqual(bytes(row.original), RAW)
        self.assertEqual(row.evidence.version, 2)
        self.assertEqual(row.event.evidence_version, 2)
        self.assertEqual(row.event.sequence, 4)
        current = cases.read_case(**staff_common(receipt))
        self.assertEqual(current["status"], "UNDER_REVIEW")
        self.assertIsNone(current["approved_answer_id"])
        self.assertEqual(
            services.staff_read(**staff_common(receipt), attachment_id=result["id"])["raw"], RAW
        )
        self.assertEqual(
            services.requester_read(
                token=receipt["token"], attachment_id=result["id"], synthetic_fixtures_only=True
            )["raw"],
            RAW,
        )

    def test_other_case_requester_staff_role_and_revoked_token_are_denied(self):
        first, other = new_case(), new_case()
        result = upload(first)
        with self.assertRaises(cases.CaseConflict):
            services.requester_read(
                token=other["token"], attachment_id=result["id"], synthetic_fixtures_only=True
            )
        for common in (
            staff_common(other),
            staff_common(first, TestDirectory([other["public_ref"]])),
            staff_common(first, TestDirectory([first["public_ref"]], role="ORGANIZER_ADMIN")),
        ):
            with self.assertRaises(cases.CaseConflict):
                services.staff_read(**common, attachment_id=result["id"])
        cases.revoke_access(
            **staff_common(first), requester_id=Case.objects.get(pk=first["case_id"]).requester_id
        )
        with self.assertRaises(cases.CaseConflict):
            services.requester_read(
                token=first["token"], attachment_id=result["id"], synthetic_fixtures_only=True
            )

    def test_file_allowlist_sizes_encoding_stale_revision_and_disabled_gate(self):
        receipt = new_case()
        for changes in (
            {"raw": b""},
            {"raw": b"x" * 65537},
            {"raw": b"a\x00b"},
            {"raw": b"\xff"},
            {"filename": "x.html"},
            {"filename": "../x.txt"},
            {"media_type": "text/html"},
            {"synthetic_fixtures_only": False},
            {"expected_revision": 2},
        ):
            with self.subTest(changes=changes.keys()), self.assertRaises(cases.CaseConflict):
                upload(receipt, **changes)
        with (
            override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            upload(receipt)
        self.assertEqual(CaseEvidence.objects.count(), 1)
        self.assertFalse(CaseAttachment.objects.exists())

    def test_upload_cannot_resolve_a_pending_clarification(self):
        receipt = new_case()
        cases.request_clarification(
            **staff_common(receipt),
            text="يرجى الرد نصيًا",
            expected_revision=1,
            expected_evidence_version=1,
        )
        with self.assertRaisesMessage(cases.CaseConflict, "requester_clarification_still_required"):
            upload(receipt, expected_revision=2)
        self.assertEqual(Case.objects.get().stage, "NEEDS_CLARIFICATION")
        self.assertFalse(CaseAttachment.objects.exists())

    def test_failed_binding_rolls_back_evidence_event_and_approval(self):
        receipt = new_case()
        with patch.object(
            CaseAttachment.objects, "create", side_effect=RuntimeError("synthetic failure")
        ):
            with self.assertRaises(RuntimeError):
                upload(receipt)
        self.assertEqual(Case.objects.get().revision, 1)
        self.assertEqual(CaseEvidence.objects.count(), 1)

    def test_db_original_and_bindings_are_immutable_and_cross_case_insert_rejected(self):
        receipt, other = new_case(), new_case()
        upload(receipt)
        row = CaseAttachment.objects.get()
        for operation in (
            lambda: CaseAttachment.objects.filter(pk=row.pk).update(original=b"new"),
            lambda: CaseAttachment.objects.filter(pk=row.pk).delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CaseAttachment.objects.create(
                case_id=other["case_id"],
                evidence=row.evidence,
                event=row.event,
                original=RAW,
                sha256=row.sha256,
                size=len(RAW),
                filename="synthetic.txt",
                subject_id=row.subject_id,
            )
        self.assertEqual(bytes(CaseAttachment.objects.get().original), RAW)

    def test_populated_guard_reverse_reapply_preserves_original(self):
        receipt = new_case()
        result = upload(receipt)
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([("case_attachments", "0001_initial")])
            self.assertEqual(bytes(CaseAttachment.objects.get(pk=result["id"]).original), RAW)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate([("case_attachments", "0002_immutable_guard")])
        with self.assertRaises(IntegrityError), transaction.atomic():
            CaseAttachment.objects.filter(pk=result["id"]).update(filename="changed.txt")
        self.assertEqual(
            services.requester_read(
                token=receipt["token"], attachment_id=result["id"], synthetic_fixtures_only=True
            )["raw"],
            RAW,
        )

    def test_concurrent_same_revision_appends_only_once(self):
        receipt = new_case()

        def attempt(_):
            connections.close_all()
            try:
                upload(receipt)
                return "saved"
            except cases.CaseConflict:
                return "stale"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertCountEqual(results, ["saved", "stale"])
        self.assertEqual(CaseAttachment.objects.count(), 1)
        self.assertEqual(CaseEvidence.objects.count(), 2)


@override_settings(
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
    FATWA_CASEWORK_WEB_ENABLED=True,
    ROOT_URLCONF="apps.case_attachments.urls",
)
class AttachmentHTTPTests(TransactionTestCase):
    def client_for(self, receipt):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/status/")
        result = post(
            client, "/casework/status/", {"action": "unlock", "token": receipt["token"]}, page
        )
        self.assertEqual(result.status_code, 303, result.content)
        page = client.get("/casework/status/")
        page = post(client, "/casework/status/", {"action": "attachments"}, page)
        self.assertEqual(page.status_code, 200, page.content)
        return client, page

    def test_actual_multipart_transfer_mufti_preview_and_other_requester_denial(self):
        first, other = new_case(), new_case()
        client, page = self.client_for(first)
        fields = {
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            "action": "attachment_upload",
            "revision": hidden(page, "revision"),
            "upload_proof": hidden(page, "upload_proof"),
            "synthetic_only": "yes",
            "attachment": SimpleUploadedFile("synthetic.txt", RAW, "text/plain"),
        }
        response = client.post("/casework/status/", fields)
        self.assertEqual(response.status_code, 200, response.content)
        row = CaseAttachment.objects.get()
        self.assertContains(response, row.sha256)
        preview = post(
            client,
            "/casework/status/",
            {"action": "attachment_preview", "attachment_id": str(row.pk)},
            response,
        )
        self.assertContains(preview, "&lt;script&gt;")
        self.assertNotContains(preview, "<script>")
        downloaded = post(
            client,
            "/casework/status/",
            {"action": "attachment_download", "attachment_id": str(row.pk)},
            response,
        )
        self.assertEqual(downloaded.content, RAW)
        self.assertIn("attachment;", downloaded["Content-Disposition"])
        self.assertIn("no-store", downloaded["Cache-Control"])
        foreign, foreign_page = self.client_for(other)
        denial = post(
            foreign,
            "/casework/status/",
            {"action": "attachment_download", "attachment_id": str(row.pk)},
            foreign_page,
        )
        self.assertEqual(denial.status_code, 409)
        self.assertNotIn(RAW, denial.content)
        directory = Directory()
        directory.grant(first["public_ref"])
        staff = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=directory):
            login = staff.get("/casework/staff/login/")
            result = post(
                staff, "/casework/staff/login/", {"credential": directory.credential}, login
            )
            self.assertEqual(result.status_code, 303)
            listing = staff.get("/casework/staff/")
            desk = post(
                staff,
                "/casework/staff/",
                {"action": "attachment_list", "case_ref": first["public_ref"]},
                listing,
            )
            self.assertContains(desk, row.sha256)
            result = post(
                staff,
                "/casework/staff/",
                {
                    "action": "attachment_download",
                    "case_ref": first["public_ref"],
                    "attachment_id": str(row.pk),
                },
                desk,
            )
            self.assertEqual(result.content, RAW)

    def test_csrf_stale_form_and_extra_upload_fields_rejected(self):
        first, other = new_case(), new_case()
        client, page = self.client_for(first)
        fields = {
            "action": "attachment_upload",
            "revision": hidden(page, "revision"),
            "upload_proof": hidden(page, "upload_proof"),
            "synthetic_only": "yes",
            "attachment": SimpleUploadedFile("synthetic.txt", RAW, "text/plain"),
        }
        self.assertEqual(client.post("/casework/status/", fields).status_code, 403)
        fields["csrfmiddlewaretoken"] = hidden(page, "csrfmiddlewaretoken")
        fields["role"] = "MUFTI"
        fields["attachment"] = SimpleUploadedFile("synthetic.txt", RAW, "text/plain")
        self.assertEqual(client.post("/casework/status/", fields).status_code, 400)
        del fields["role"]
        switched = post(
            client, "/casework/status/", {"action": "unlock", "token": other["token"]}, page
        )
        self.assertEqual(switched.status_code, 303)
        fields["attachment"] = SimpleUploadedFile("synthetic.txt", RAW, "text/plain")
        self.assertEqual(client.post("/casework/status/", fields).status_code, 409)
        self.assertFalse(CaseAttachment.objects.exists())
