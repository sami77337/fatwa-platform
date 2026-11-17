"""Actual native-form requests and denial paths on a fresh owned PostgreSQL DB."""

from dataclasses import replace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase, override_settings

from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvidence
from tests.casework.test_http import WEB_SETTINGS, Directory, hidden, post

from . import desk_services, services, simulators
from .models import EvidenceBinding

DESK_SETTINGS = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "apps.source_case_intake.urls",
    "FATWA_SOURCE_CASE_INTAKE_ENABLED": True,
    "FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
}
PATH = "/casework/staff/"


def receive(raw, source="telegram"):
    return services.ingest(
        raw=raw, context=simulators.context(source), synthetic_fixtures_only=True
    )


@override_settings(**DESK_SETTINGS)
class SourceDeskHTTPTests(TransactionTestCase):
    def test_raw_preview_is_escaped_exact_and_invalid_utf8_uses_hex(self):
        text = b'{"unrecognized":"<script>alert(1)</script>"}\r\n'
        held = receive(text)
        result = post(
            self.client,
            PATH,
            {"action": "source_raw_view", "receipt_id": held["receipt_id"]},
            self.page,
        )
        self.assertContains(result, "&lt;script&gt;")
        self.assertNotContains(result, "<script>")
        self.assertContains(result, "UTF-8")
        bad = receive(b"\xff\x00\x0a")
        result = post(
            self.client,
            PATH,
            {"action": "source_raw_view", "receipt_id": bad["receipt_id"]},
            self.page,
        )
        self.assertContains(result, "ff 00 0a")
        denied = post(
            self.client,
            PATH,
            {"action": "source_raw_view", "receipt_id": self.foreign["receipt_id"]},
            self.page,
        )
        self.assertEqual(denied.status_code, 409)

    def test_pending_receipt_can_resume_once_without_bypassing_review(self):
        pending = services.capture(
            raw=simulators.telegram(8, parent=999),
            context=simulators.context("telegram"),
            synthetic_fixtures_only=True,
        )
        page = self.open({"receipt_id": str(pending.pk)})
        self.assertContains(page, "استئناف معالجة الحدث المحفوظ")
        fields = {
            "action": "source_resume",
            "receipt_id": str(pending.pk),
            "proof": hidden(page, "proof"),
            "confirm": "yes",
        }
        result = post(self.client, PATH, fields, page)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(services._result(pending)["status"], "NEEDS_REVIEW")
        self.assertEqual(services._result(pending)["reason"], "parent_unresolved")
        self.assertEqual(post(self.client, PATH, fields, page).status_code, 409)
        self.assertFalse(EvidenceBinding.objects.filter(receipt=pending).exists())

    def setUp(self):
        self.root = receive(simulators.telegram(document=True))
        self.held = receive(simulators.telegram(2, parent=1))
        self.foreign = receive(simulators.telegram(3, sender=200))
        self.directory = Directory()
        self.directory.grant(services.REVIEW_SCOPE, self.root["public_ref"])
        self.identity_settings = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        self.identity_settings.enable()
        self.addCleanup(self.identity_settings.disable)
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        page = self.client.get(PATH + "login/")
        login = post(self.client, PATH + "login/", {"credential": self.directory.credential}, page)
        self.assertEqual(login.status_code, 303)
        self.page = self.client.get(PATH)
        self.assertEqual(self.page.status_code, 200)

    def open(self, result):
        return post(
            self.client,
            PATH,
            {"action": "source_open", "receipt_id": result["receipt_id"]},
            self.page,
        )

    def decision(self, page, result=None, **changes):
        fields = {
            "action": "source_resolve",
            "receipt_id": (result or self.held)["receipt_id"],
            "proof": hidden(page, "proof"),
            "decision": "FOLLOWUP",
            "note": "سبب بشري اصطناعي",
            "case_id": self.root["case_id"],
            "token": self.root["token"],
            "confirm": "yes",
        }
        return {**fields, **changes}

    def test_scoped_listing_filters_detail_and_raw_download(self):
        self.assertContains(self.page, self.root["public_ref"])
        self.assertNotContains(self.page, self.foreign["public_ref"])
        filtered = post(
            self.client,
            PATH,
            {"action": "source_filter", "source": "telegram", "state": "review", "page": "1"},
            self.page,
        )
        self.assertContains(filtered, self.held["receipt_id"])
        self.assertNotContains(filtered, self.root["receipt_id"])
        page = self.open(self.root)
        self.assertContains(page, "source-question")
        raw = post(
            self.client, PATH, {"action": "source_raw", "receipt_id": self.root["receipt_id"]}, page
        )
        self.assertEqual(raw.content, simulators.telegram(document=True))
        self.assertEqual(raw["Content-Type"], "application/octet-stream")
        self.assertIn("attachment", raw["Content-Disposition"])
        self.assertIn("no-store", raw["Cache-Control"])
        self.assertEqual(raw["X-Content-Type-Options"], "nosniff")

    def test_bound_foreign_raw_and_unbound_without_review_scope_are_denied(self):
        for action in ("source_open", "source_raw"):
            response = post(
                self.client,
                PATH,
                {"action": action, "receipt_id": self.foreign["receipt_id"]},
                self.page,
            )
            self.assertEqual(response.status_code, 409)
            self.assertNotIn(simulators.telegram(3, sender=200), response.content)
        self.directory.grant(self.root["public_ref"])
        denied = self.open(self.held)
        self.assertEqual(denied.status_code, 409)
        listing = self.client.get(PATH)
        self.assertNotContains(listing, self.held["receipt_id"])

    def test_human_followup_is_atomic_audited_and_cannot_repeat(self):
        page = self.open(self.held)
        fields = self.decision(page)
        result = post(self.client, PATH, fields, page)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertNotIn(self.root["token"].encode(), result.content)
        binding = EvidenceBinding.objects.get(receipt_id=self.held["receipt_id"])
        self.assertEqual(str(binding.case_id), self.root["case_id"])
        self.assertEqual(binding.review_note, fields["note"])
        self.assertEqual(binding.subject_id, self.directory.current.subject_id)
        repeat = post(self.client, PATH, fields, page)
        self.assertEqual(repeat.status_code, 409)
        self.assertEqual(Case.objects.get(pk=self.root["case_id"]).evidence_version, 2)

    def test_human_split_does_not_grant_new_case_scope_or_expose_capability(self):
        page = self.open(self.held)
        fields = self.decision(page, decision="NEW_CASE", case_id="", token="")
        response = post(self.client, PATH, fields, page)
        self.assertEqual(response.status_code, 200)
        binding = EvidenceBinding.objects.get(receipt_id=self.held["receipt_id"])
        self.assertNotEqual(str(binding.case_id), self.root["case_id"])
        self.assertContains(response, binding.case.public_ref)
        self.assertNotIn(binding.case.public_ref, self.directory.current.case_keys)
        self.assertNotIn(b"rt_", response.content)
        self.assertEqual(self.open(self.held).status_code, 409)

    def test_stale_evidence_rejects_old_review_form(self):
        page = self.open(self.held)
        fields = self.decision(page)
        cases.add_followup(
            token=self.root["token"],
            text="وقائع جديدة",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        result = post(self.client, PATH, fields, page)
        self.assertEqual(result.status_code, 409)
        self.assertFalse(
            EvidenceBinding.objects.filter(receipt_id=self.held["receipt_id"]).exists()
        )

    def test_unoffered_cross_person_case_token_and_tampered_proof_are_denied(self):
        page = self.open(self.held)
        for changes, status in (
            ({"case_id": self.foreign["case_id"]}, 400),
            ({"token": self.foreign["token"]}, 409),
            ({"proof": "tampered"}, 400),
            ({"confirm": "no"}, 400),
        ):
            with self.subTest(changes=changes):
                response = post(self.client, PATH, self.decision(page, **changes), page)
                self.assertEqual(response.status_code, status)
        self.assertFalse(
            EvidenceBinding.objects.filter(receipt_id=self.held["receipt_id"]).exists()
        )

    def test_conflicted_source_cannot_be_resolved_by_form(self):
        changed = receive(simulators.telegram(document=True) + b" ")
        page = self.open(changed)
        self.assertContains(page, "بايتات مختلفة")
        self.assertNotContains(page, 'id="split-form"')
        fields = (
            self.decision(page, result=changed, decision="NEW_CASE", case_id="", token="")
            if b'name="proof"' in page.content
            else None
        )
        # Direct forged resolve still needs a genuine, same-receipt browser proof.
        if fields is None:
            root_page = self.open(self.held)
            fields = self.decision(
                root_page, result=changed, decision="NEW_CASE", case_id="", token=""
            )
        result = post(self.client, PATH, fields, page)
        self.assertIn(result.status_code, (400, 409))

    def upload(self, page, **changes):
        fields = {
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            "action": "source_attach",
            "receipt_id": self.root["receipt_id"],
            "proof": hidden(page, "proof"),
            "source_file_id": "synthetic-file-1",
            "token": self.root["token"],
            "confirm": "yes",
            "attachment": SimpleUploadedFile("synthetic.txt", b"synthetic file", "text/plain"),
        }
        return self.client.post(PATH, {**fields, **changes})

    def test_actual_upload_timeline_private_file_and_raw_origin(self):
        page = self.open(self.root)
        result = self.upload(page)
        self.assertEqual(result.status_code, 200, result.content)
        row = CaseAttachment.objects.get()
        timeline = post(
            self.client,
            PATH,
            {"action": "source_timeline", "case_ref": self.root["public_ref"]},
            result,
        )
        self.assertContains(timeline, 'data-evidence-version="2"')
        self.assertContains(timeline, "synthetic-file-1")
        self.assertContains(timeline, row.sha256)
        file = self.client.get(f"/casework/staff/attachments/{row.pk}/")
        self.assertEqual(file.content, b"synthetic file")
        replay = self.upload(self.open(self.root))
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(CaseAttachment.objects.count(), 1)

    def test_upload_stale_versions_foreign_capability_and_scope_revocation(self):
        page = self.open(self.root)
        self.assertEqual(self.upload(page, token=self.foreign["token"]).status_code, 409)
        cases.add_followup(
            token=self.root["token"],
            text="تغيير الوقائع",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(self.upload(page).status_code, 409)
        page = self.open(self.root)
        original = services.attachments._validate

        def revoke(*args, **kwargs):
            checked = original(*args, **kwargs)
            self.directory.grant(services.REVIEW_SCOPE)
            return checked

        with patch.object(services.attachments, "_validate", side_effect=revoke):
            self.assertEqual(self.upload(page).status_code, 409)
        self.assertFalse(CaseAttachment.objects.exists())

    def test_csrf_query_method_role_epoch_and_disabled_flag(self):
        self.assertEqual(self.client.post(PATH, {"action": "source_inbox"}).status_code, 403)
        self.assertEqual(self.client.get(PATH + "?receipt=anything").status_code, 400)
        self.assertEqual(self.client.put(PATH).status_code, 405)
        with override_settings(FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED=False):
            self.assertEqual(self.client.get(PATH).status_code, 503)
        self.directory.current = replace(self.directory.current, role="ORGANIZER_ADMIN")
        self.assertEqual(self.client.get(PATH).status_code, 403)
        self.directory.current = replace(self.directory.current, role="MUFTI", auth_epoch="epoch-2")
        self.assertEqual(self.client.get(PATH).status_code, 403)
        self.assertEqual(CaseEvidence.objects.count(), 2)

    def test_pagination_and_no_scope_leak_in_candidate_choices(self):
        for number in range(10, 36):
            receive(simulators.telegram(number, parent=999))
        listing = desk_services.inbox(
            subject_id=self.directory.current.subject_id,
            provider=self.directory,
            state="review",
            synthetic_fixtures_only=True,
        )
        self.assertEqual(len(listing["receipts"]), 25)
        self.assertEqual(listing["next_page"], 2)
        second = post(
            self.client,
            PATH,
            {"action": "source_filter", "source": "all", "state": "review", "page": "2"},
            self.page,
        )
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "الصفحة السابقة")
        detail = self.open(self.held)
        self.assertNotContains(detail, self.foreign["case_id"])
