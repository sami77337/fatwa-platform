"""Focused V11 source workflow tests on owned PostgreSQL; no real account data."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseEvidence
from tests.casework.test_http import hidden, post

from . import desk_services, http_tests, services, simulators
from .http_tests import DESK_SETTINGS, PATH, receive
from .models import EvidenceBinding, SourceReceipt, SourceReviewNote

V11_SETTINGS = {**DESK_SETTINGS, "FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED": True}


@override_settings(**V11_SETTINGS)
class V11SourceDeskTests(TransactionTestCase):
    setUp = http_tests.SourceDeskHTTPTests.setUp
    open = http_tests.SourceDeskHTTPTests.open
    decision = http_tests.SourceDeskHTTPTests.decision
    upload = http_tests.SourceDeskHTTPTests.upload

    def common(self):
        return dict(
            subject_id=self.directory.current.subject_id,
            provider=self.directory,
            synthetic_fixtures_only=True,
        )

    def note_fields(self, page, *, kind="NOTE", note="ملاحظة متابعة بشرية", receipt=None):
        return dict(
            action="source_note",
            receipt_id=(receipt or self.held)["receipt_id"],
            proof=hidden(page, "proof"),
            kind=kind,
            note=note,
            confirm="yes",
        )

    def test_three_source_simulators_capture_once_and_do_not_append_before_review(self):
        youtube, website = (
            receive(simulators.youtube(), "youtube"),
            receive(simulators.website(), "website"),
        )
        self.directory.grant(
            services.REVIEW_SCOPE,
            self.root["public_ref"],
            youtube["public_ref"],
            website["public_ref"],
        )
        count = SourceReceipt.objects.count()
        for root in (self.root, youtube, website):
            with self.subTest(root=root["public_ref"]):
                page = self.open(root)
                fields = dict(
                    action="source_simulate",
                    receipt_id=root["receipt_id"],
                    case_ref=root["public_ref"],
                    scenario="reply",
                    proof=hidden(page, "proof"),
                    confirm="yes",
                )
                result = post(self.client, PATH, fields, page)
                self.assertEqual(result.status_code, 200, result.content)
                self.assertContains(result, 'id="followup-form"')
                count += 1
                self.assertEqual(SourceReceipt.objects.count(), count)
                repeated = post(self.client, PATH, fields, page)
                self.assertEqual(repeated.status_code, 200)
                self.assertEqual(SourceReceipt.objects.count(), count)
                self.assertEqual(Case.objects.get(pk=root["case_id"]).evidence_version, 1)
        self.assertEqual(Case.objects.count(), 4)  # includes pre-existing foreign fixture

    def test_simulator_same_name_foreign_sender_is_not_offered_a_case(self):
        page = self.open(self.root)
        result = post(
            self.client,
            PATH,
            dict(
                action="source_simulate",
                receipt_id=self.root["receipt_id"],
                scenario="other_sender",
                proof=hidden(page, "proof"),
                confirm="yes",
            ),
            page,
        )
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "اسم تجريبي متكرر")
        self.assertNotContains(result, 'id="followup-form"')
        self.assertContains(result, 'id="split-form"')
        self.assertEqual(CaseEvidence.objects.count(), 2)

    def test_simulator_replay_flag_scope_confirmation_and_untrusted_form(self):
        page = self.open(self.root)
        fields = dict(
            action="source_simulate",
            receipt_id=self.root["receipt_id"],
            scenario="replay",
            proof=hidden(page, "proof"),
            confirm="yes",
        )
        count = SourceReceipt.objects.count()
        self.assertEqual(post(self.client, PATH, fields, page).status_code, 200)
        self.assertEqual(SourceReceipt.objects.count(), count)
        for changes, status in (
            ({"proof": "bad"}, 400),
            ({"confirm": "no"}, 400),
            ({"scenario": "whatsapp"}, 409),
            ({"sender": "injected"}, 400),
            ({"case_ref": self.foreign["public_ref"]}, 400),
        ):
            self.assertEqual(
                post(self.client, PATH, {**fields, **changes}, page).status_code, status
            )
        with override_settings(FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED=False):
            self.assertEqual(post(self.client, PATH, fields, page).status_code, 409)
        self.directory.grant(self.root["public_ref"])
        self.assertEqual(post(self.client, PATH, fields, page).status_code, 409)
        self.assertEqual(SourceReceipt.objects.count(), count)

    def test_hold_reopen_note_audit_and_stale_resolution(self):
        page = self.open(self.held)
        original = bytes(SourceReceipt.objects.get(pk=self.held["receipt_id"]).raw)
        old_resolution = self.decision(page)
        fields = self.note_fields(page, kind="HOLD", note="بانتظار تحقق بشري من تسلسل المحادثة")
        held = post(self.client, PATH, fields, page)
        self.assertEqual(held.status_code, 200, held.content)
        self.assertContains(held, "أُجّلت المراجعة")
        self.assertNotContains(held, 'id="followup-form"')
        self.assertEqual(post(self.client, PATH, fields, page).status_code, 200)
        self.assertEqual(SourceReviewNote.objects.count(), 1)
        self.assertEqual(
            post(self.client, PATH, {**fields, "note": "مختلف"}, page).status_code, 409
        )
        with self.assertRaisesMessage(services.IntakeError, "source_review_on_hold"):
            services.resolve_review(
                **self.common(),
                receipt_id=self.held["receipt_id"],
                action="NEW_CASE",
                note="محاولة تجاوز",
            )
        reopened = post(
            self.client, PATH, self.note_fields(held, kind="REOPEN", note="اكتمل التحقق"), held
        )
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(post(self.client, PATH, old_resolution, page).status_code, 409)
        resolved = post(self.client, PATH, self.decision(reopened), reopened)
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(SourceReviewNote.objects.count(), 2)
        self.assertEqual(bytes(SourceReceipt.objects.get(pk=self.held["receipt_id"]).raw), original)
        self.assertEqual(
            EvidenceBinding.objects.get(receipt_id=self.held["receipt_id"]).case_id,
            Case.objects.get(pk=self.root["case_id"]).pk,
        )

    def test_search_return_context_does_not_leak_other_cases(self):
        fields = dict(
            action="source_filter",
            source="telegram",
            state="bound",
            page="1",
            query=self.root["public_ref"],
        )
        result = post(self.client, PATH, fields, self.page)
        self.assertContains(result, self.root["receipt_id"])
        self.assertNotContains(result, self.foreign["receipt_id"])
        page = self.open(self.root)
        returned = post(self.client, PATH, {"action": "source_return"}, page)
        self.assertContains(returned, 'value="' + self.root["public_ref"] + '"')
        self.assertNotContains(returned, self.foreign["receipt_id"])
        denied = post(self.client, PATH, {**fields, "query": self.foreign["public_ref"]}, returned)
        self.assertNotContains(denied, self.foreign["receipt_id"])
        arabic = post(self.client, PATH, {**fields, "query": "بدون إعادة صياغة"}, returned)
        self.assertContains(arabic, self.root["receipt_id"])
        self.assertNotContains(arabic, self.foreign["receipt_id"])

    def test_hold_and_missing_file_filters_and_cross_case_note_denial(self):
        page = self.open(self.held)
        held = post(self.client, PATH, self.note_fields(page, kind="HOLD"), page)
        result = post(
            self.client,
            PATH,
            dict(action="source_filter", source="all", state="held", page="1"),
            held,
        )
        self.assertContains(result, self.held["receipt_id"])
        self.assertNotContains(result, self.root["receipt_id"])
        files = post(
            self.client,
            PATH,
            dict(action="source_filter", source="all", state="files", page="1"),
            result,
        )
        self.assertContains(files, self.root["receipt_id"])
        self.assertNotContains(files, self.held["receipt_id"])
        self.assertEqual(self.upload(self.open(self.root)).status_code, 200)
        files = post(
            self.client,
            PATH,
            dict(action="source_filter", source="all", state="files", page="1"),
            result,
        )
        self.assertNotContains(files, self.root["receipt_id"])
        with self.assertRaises(cases.CaseConflict):
            desk_services.record_note(
                **self.common(),
                receipt_id=self.foreign["receipt_id"],
                kind="NOTE",
                text="غير مخول",
                request_key="foreign",
                expected_sequence=0,
            )

    def test_note_scope_revocation_rolls_back(self):
        original = SourceReviewNote.objects.create

        def revoke(**kwargs):
            result = original(**kwargs)
            self.directory.grant("unrelated")
            return result

        with patch.object(SourceReviewNote.objects, "create", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                desk_services.record_note(
                    **self.common(),
                    receipt_id=self.root["receipt_id"],
                    kind="NOTE",
                    text="ملاحظة لا تحفظ بعد سحب النطاق",
                    request_key="revoked",
                    expected_sequence=0,
                )
        self.assertFalse(SourceReviewNote.objects.exists())

    def test_concurrent_notes_same_version_only_one_wins(self):
        def attempt(number):
            connections.close_all()
            try:
                desk_services.record_note(
                    **self.common(),
                    receipt_id=self.held["receipt_id"],
                    kind="NOTE",
                    text="ملاحظة اصطناعية",
                    request_key=f"request-{number}",
                    expected_sequence=0,
                )
                return "saved"
            except services.IntakeError:
                return "stale"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(attempt, range(2))), ["saved", "stale"])
        self.assertEqual(SourceReviewNote.objects.count(), 1)

    def test_note_guard_reversal_reapply_and_immutable_history(self):
        desk_services.record_note(
            **self.common(),
            receipt_id=self.held["receipt_id"],
            kind="NOTE",
            text="تاريخ محفوظ",
            request_key="immutable",
            expected_sequence=0,
        )
        try:
            MigrationExecutor(connection).migrate([("source_case_intake", "0003_sourcereviewnote")])
            self.assertEqual(SourceReviewNote.objects.get().text, "تاريخ محفوظ")
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        for operation in (
            lambda: SourceReviewNote.objects.update(text="changed"),
            lambda: SourceReviewNote.objects.all().delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        self.assertEqual(SourceReviewNote.objects.get().text, "تاريخ محفوظ")
