"""Focused real PostgreSQL tests; all provider objects and people are fabricated."""

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.template.loader import render_to_string
from django.test import TransactionTestCase, override_settings

from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvidence
from tests.casework.test_core import TestDirectory

from . import services as s
from . import simulators as f
from .adapters import IntakeError, SourceContext
from .models import AttachmentBinding, EvidenceBinding, ReviewTicket, SourceReceipt


@override_settings(FATWA_SOURCE_CASE_INTAKE_ENABLED=True, FATWA_CASE_ATTACHMENTS_ENABLED=True)
class SourceIntakeTests(TransactionTestCase):
    def test_unthreaded_message_is_reviewed_before_split_or_append(self):
        root = self.ingest()
        held = self.ingest(f.telegram(2))
        self.assertEqual(held["reason"], "unthreaded_message_requires_review")
        self.assertEqual(Case.objects.count(), 1)
        separated = self.review(held)
        self.assertNotEqual(separated["case_id"], root["case_id"])
        another = self.ingest(f.telegram(3))
        provider = TestDirectory([s.REVIEW_SCOPE, root["public_ref"]])
        linked = self.review(
            another, "FOLLOWUP", provider=provider, case_id=root["case_id"], token=root["token"]
        )
        self.assertEqual(linked["case_id"], root["case_id"])

    def test_review_authority_revocation_rolls_back_binding_and_case(self):
        held = self.ingest(f.telegram(2, parent=99))
        provider = TestDirectory([s.REVIEW_SCOPE])
        original = s._new_case

        def revoke_after_create(*args, **kwargs):
            result = original(*args, **kwargs)
            provider.epoch = "epoch-2"
            return result

        with patch.object(s, "_new_case", side_effect=revoke_after_create):
            with self.assertRaisesMessage(IntakeError, "review_identity_changed"):
                self.review(held, provider=provider)
        self.assertFalse(Case.objects.exists())
        self.assertFalse(EvidenceBinding.objects.exists())
        self.assertEqual(ReviewTicket.objects.count(), 1)

    def test_youtube_trusted_conversation_cannot_change_on_raw_replay(self):
        self.ingest(f.youtube(), "youtube")
        with self.assertRaisesMessage(IntakeError, "source_context_changed"):
            self.ingest(
                f.youtube(), "youtube", context=f.context("youtube", conversation="other-video")
            )
        self.assertEqual(Case.objects.count(), 1)

    def ingest(self, raw=None, source="telegram", **kwargs):
        return s.ingest(
            raw=f.telegram() if raw is None else raw,
            context=kwargs.pop("context", f.context(source)),
            synthetic_fixtures_only=True,
            **kwargs,
        )

    def staff(self, receipt, provider=None):
        return dict(
            case_id=receipt["case_id"],
            subject_id="synthetic-mufti",
            provider=provider or TestDirectory([receipt["public_ref"]]),
            synthetic_fixtures_only=True,
        )

    def review(self, receipt, action="NEW_CASE", **kwargs):
        return s.resolve_review(
            receipt_id=receipt["receipt_id"],
            action=action,
            note="قرار ربط بشري اصطناعي",
            subject_id="synthetic-mufti",
            provider=kwargs.pop("provider", TestDirectory([s.REVIEW_SCOPE])),
            synthetic_fixtures_only=True,
            **kwargs,
        )

    def test_three_sources_create_and_reply_using_same_canonical_case(self):
        for source in ("telegram", "youtube", "website"):
            with self.subTest(source=source):
                fixture = getattr(f, source)
                original = fixture()
                root = self.ingest(original, source)
                reply = self.ingest(fixture(2, parent=1), source, token=root["token"])
                self.assertEqual(reply["status"], "FOLLOWUP")
                self.assertEqual(reply["case_id"], root["case_id"])
                self.assertEqual(reply["evidence_version"], 2)
                self.assertEqual(
                    bytes(SourceReceipt.objects.get(pk=root["receipt_id"]).raw), original
                )
                origins = s.staff_origins(**self.staff(root))
                self.assertEqual([r["source"] for r in origins], [source, source])
                self.assertEqual([r["evidence_version"] for r in origins], [1, 2])
        self.assertEqual(Case.objects.count(), 3)
        self.assertEqual(CaseEvidence.objects.count(), 6)

    def test_replay_retains_bytes_returns_no_capability_and_no_duplicate_evidence(self):
        root = self.ingest()
        replay = self.ingest()
        self.assertEqual(root["receipt_id"], replay["receipt_id"])
        self.assertIsNone(replay["token"])
        self.assertEqual(SourceReceipt.objects.count(), 1)
        self.assertEqual(CaseEvidence.objects.count(), 1)
        self.assertEqual(
            s.staff_raw(
                receipt_id=root["receipt_id"],
                **{k: v for k, v in self.staff(root).items() if k != "case_id"},
            ),
            f.telegram(),
        )

    def test_changed_bytes_with_same_event_id_are_retained_for_review(self):
        root = self.ingest()
        changed = f.telegram() + b" "
        conflict = self.ingest(changed)
        self.assertEqual(conflict["reason"], "event_idempotency_conflict")
        self.assertEqual(bytes(SourceReceipt.objects.get(pk=conflict["receipt_id"]).raw), changed)
        with self.assertRaisesMessage(IntakeError, "correlation_review_required"):
            self.review(conflict)
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(self.ingest()["case_id"], root["case_id"])

    def test_message_identity_dedup_across_distinct_update_ids(self):
        self.ingest()
        data = json.loads(f.telegram())
        data["update_id"] = 9999
        duplicate = self.ingest(f.raw(data))
        self.assertEqual(duplicate["reason"], "message_already_bound")
        self.assertEqual(Case.objects.count(), 1)

    def test_identical_names_do_not_merge_senders_accounts_or_conversations(self):
        first = self.ingest()
        foreign = self.ingest(f.telegram(2, sender=200, parent=1), token=first["token"])
        self.assertEqual(foreign["reason"], "source_identity_or_thread_mismatch")
        provider = TestDirectory([s.REVIEW_SCOPE, first["public_ref"]])
        with self.assertRaisesMessage(IntakeError, "source_case_identity_mismatch"):
            self.review(
                foreign,
                "FOLLOWUP",
                provider=provider,
                case_id=first["case_id"],
                token=first["token"],
            )
        separated = self.review(foreign)
        self.assertNotEqual(separated["case_id"], first["case_id"])
        another_account = self.ingest(context=f.context("telegram", account="synthetic-other"))
        self.assertNotEqual(another_account["case_id"], first["case_id"])
        cross_account_reply = self.ingest(
            f.telegram(3, parent=1), context=f.context("telegram", account="synthetic-third")
        )
        self.assertEqual(cross_account_reply["reason"], "parent_unresolved")
        data = json.loads(f.telegram(4, parent=1))
        data["message"]["chat"]["id"] = -100999
        self.assertEqual(self.ingest(f.raw(data))["reason"], "parent_unresolved")

    def test_threads_edits_and_unavailable_original_are_held(self):
        root = self.ingest(f.telegram(thread=10))
        reply = self.ingest(f.telegram(2, parent=1, thread=11), token=root["token"])
        self.assertEqual(reply["reason"], "source_identity_or_thread_mismatch")
        edited = json.loads(f.telegram())
        edited["edited_message"] = edited.pop("message")
        edited["update_id"] = 2001
        self.assertEqual(self.ingest(f.raw(edited))["reason"], "source_edit_requires_review")
        comment = json.loads(f.youtube())
        del comment["snippet"]["textOriginal"]
        held = self.ingest(f.raw(comment), "youtube")
        self.assertEqual(held["status"], "NEEDS_REVIEW")
        self.assertEqual(SourceReceipt.objects.get(pk=held["receipt_id"]).original_text, "")

    def test_unknown_parent_requires_explicit_human_review_even_after_parent_arrives(self):
        reply = self.ingest(f.telegram(2, parent=1))
        self.assertEqual(reply["reason"], "parent_unresolved")
        root = self.ingest()
        self.assertEqual(
            self.ingest(f.telegram(2, parent=1), token=root["token"])["status"], "NEEDS_REVIEW"
        )
        provider = TestDirectory([s.REVIEW_SCOPE, root["public_ref"]])
        result = self.review(
            reply, "FOLLOWUP", provider=provider, case_id=root["case_id"], token=root["token"]
        )
        self.assertEqual(result["case_id"], root["case_id"])
        self.assertEqual(result["evidence_version"], 2)
        self.assertTrue(ReviewTicket.objects.filter(receipt_id=reply["receipt_id"]).exists())
        binding = EvidenceBinding.objects.get(receipt_id=reply["receipt_id"])
        self.assertEqual(binding.subject_id, "synthetic-mufti")
        self.assertEqual(binding.auth_epoch, "epoch-1")
        with self.assertRaisesMessage(IntakeError, "receipt_already_resolved"):
            self.review(reply)

    def test_missing_wrong_and_revoked_capability_cannot_append(self):
        root = self.ingest()
        held = self.ingest(f.telegram(2, parent=1))
        self.assertEqual(held["reason"], "case_capability_required")
        other = self.ingest(f.telegram(3, sender=300))
        with self.assertRaisesMessage(IntakeError, "source_case_identity_mismatch"):
            self.ingest(f.telegram(4, parent=1), token=other["token"])
        cases.revoke_access(
            **self.staff(root), requester_id=Case.objects.get(pk=root["case_id"]).requester_id
        )
        with self.assertRaises(cases.CaseConflict):
            self.ingest(f.telegram(5, parent=1), token=root["token"])
        self.assertEqual(Case.objects.get(pk=root["case_id"]).evidence_version, 1)
        self.assertEqual(SourceReceipt.objects.count(), 5)  # failed apply still captured

    def test_raw_survives_apply_failure_and_retry_is_atomic(self):
        with patch.object(EvidenceBinding.objects, "create", side_effect=RuntimeError("fixture")):
            with self.assertRaises(RuntimeError):
                self.ingest()
        self.assertEqual(SourceReceipt.objects.count(), 1)
        self.assertEqual(Case.objects.count(), 0)
        self.assertEqual(CaseEvidence.objects.count(), 0)
        self.assertEqual(self.ingest()["status"], "CREATED")
        self.assertEqual(SourceReceipt.objects.count(), 1)

    def test_malformed_duplicate_json_and_unknown_events_preserve_raw_without_case(self):
        for raw in (
            b"{bad",
            b"\xff",
            b'{"update_id":1,"update_id":2}',
            b'{"update_id":7,"message":null}',
            b'{"value":"\\ud800"}',
            b'{"value":"\\u0000"}',
            b'{"value":NaN}',
        ):
            result = self.ingest(raw)
            self.assertEqual(result["status"], "NEEDS_REVIEW")
            self.assertEqual(bytes(SourceReceipt.objects.get(pk=result["receipt_id"]).raw), raw)
        self.assertFalse(Case.objects.exists())

    def test_closed_flags_synthetic_ack_unknown_source_and_bounds(self):
        with override_settings(FATWA_SOURCE_CASE_INTAKE_ENABLED=False):
            with self.assertRaisesMessage(IntakeError, "source_intake_disabled"):
                self.ingest()
        with self.assertRaises(cases.CaseConflict):
            s.ingest(raw=f.telegram(), context=f.context("telegram"))
        for context in (
            SourceContext("facebook", "synthetic-account"),
            SourceContext("telegram", "live-account"),
        ):
            with self.assertRaises(IntakeError):
                self.ingest(context=context)
        for raw in (b"", b"x" * 262145):
            with self.assertRaises(IntakeError):
                self.ingest(raw)
        with transaction.atomic(), self.assertRaisesMessage(IntakeError, "independent_commit"):
            self.ingest()
        self.assertFalse(SourceReceipt.objects.exists())

    def test_review_scope_is_separate_and_origin_reads_are_case_scoped(self):
        root = self.ingest()
        held = self.ingest(f.telegram(3, parent=99))
        foreign = TestDirectory(["unrelated-case"])
        with self.assertRaises(cases.CaseConflict):
            s.staff_origins(**self.staff(root, foreign))
        with self.assertRaises(IntakeError):
            self.review(held, provider=TestDirectory([root["public_ref"]]))
        with self.assertRaises(IntakeError):
            s.review_queue(
                subject_id="synthetic-mufti", provider=foreign, synthetic_fixtures_only=True
            )
        with self.assertRaises(cases.CaseConflict):
            s.staff_raw(
                receipt_id=root["receipt_id"],
                subject_id="synthetic-mufti",
                provider=TestDirectory([s.REVIEW_SCOPE]),
                synthetic_fixtures_only=True,
            )
        queue = s.review_queue(
            subject_id="synthetic-mufti",
            provider=TestDirectory([s.REVIEW_SCOPE]),
            synthetic_fixtures_only=True,
        )
        self.assertEqual([x["receipt_id"] for x in queue], [held["receipt_id"]])

    def test_followup_invalidates_existing_human_approval(self):
        root = self.ingest()
        draft = cases.save_answer(
            **self.staff(root),
            text="جواب بشري اصطناعي",
            expected_revision=1,
            expected_evidence_version=1,
        )
        cases.record_decision(
            **self.staff(root),
            answer_id=draft["answers"][0]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        self.ingest(f.telegram(2, parent=1), token=root["token"])
        case = Case.objects.get(pk=root["case_id"])
        self.assertIsNone(case.approved_answer_id)
        self.assertEqual(case.stage, "UNDER_REVIEW")

    def test_v8_attachment_upload_idempotency_and_cross_case_denial(self):
        root = self.ingest(f.telegram(document=True))
        other = self.ingest(f.telegram(2, sender=200))
        args = dict(
            receipt_id=root["receipt_id"],
            source_file_id="synthetic-file-1",
            token=root["token"],
            raw="مرفق اصطناعي".encode(),
            filename="synthetic.txt",
            media_type="text/plain",
            synthetic_fixtures_only=True,
        )
        with self.assertRaisesMessage(IntakeError, "source_case_identity_mismatch"):
            s.attach_fixture(**{**args, "token": other["token"]})
        with self.assertRaisesMessage(IntakeError, "declared_bound_attachment_required"):
            s.attach_fixture(**{**args, "source_file_id": "invented-file"})
        result = s.attach_fixture(**args)
        self.assertTrue(result["created"])
        self.assertFalse(s.attach_fixture(**args)["created"])
        with self.assertRaisesMessage(IntakeError, "attachment_idempotency_conflict"):
            s.attach_fixture(**{**args, "raw": b"changed"})
        self.assertEqual(CaseAttachment.objects.count(), 1)
        self.assertEqual(Case.objects.get(pk=root["case_id"]).evidence_version, 2)
        self.assertEqual(CaseAttachment.objects.get().source, "REQUESTER_UPLOAD")
        self.assertEqual(
            AttachmentBinding.objects.get().attachment_id, CaseAttachment.objects.get().pk
        )

    def test_attachment_validation_and_failed_binding_rollback_v8_evidence(self):
        root = self.ingest(f.telegram(document=True))
        args = dict(
            receipt_id=root["receipt_id"],
            source_file_id="synthetic-file-1",
            token=root["token"],
            raw=b"fixture",
            filename="synthetic.txt",
            media_type="text/plain",
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            s.attach_fixture(**{**args, "filename": "../escape.txt"})
        with patch.object(AttachmentBinding.objects, "create", side_effect=RuntimeError("fixture")):
            with self.assertRaises(RuntimeError):
                s.attach_fixture(**args)
        self.assertFalse(CaseAttachment.objects.exists())
        self.assertEqual(Case.objects.get().evidence_version, 1)

    def test_db_raw_binding_immutability_and_cross_case_rejection(self):
        root = self.ingest()
        other = self.ingest(f.telegram(2, sender=200))
        for operation in (
            lambda: SourceReceipt.objects.filter(pk=root["receipt_id"]).update(raw=b"new"),
            lambda: SourceReceipt.objects.filter(pk=root["receipt_id"]).delete(),
            lambda: EvidenceBinding.objects.filter(receipt_id=root["receipt_id"]).update(
                case_id=other["case_id"]
            ),
            lambda: EvidenceBinding.objects.filter(receipt_id=root["receipt_id"]).delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        pending = s.capture(
            raw=f.telegram(3, sender=300),
            context=f.context("telegram"),
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            EvidenceBinding.objects.create(
                receipt=pending,
                message_key=pending.message_key,
                case_id=root["case_id"],
                evidence=CaseEvidence.objects.get(case_id=other["case_id"]),
                action="CREATED",
            )

    def test_concurrent_identical_ingest_creates_once(self):
        def attempt(_):
            connections.close_all()
            try:
                return self.ingest()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(results[0]["case_id"], results[1]["case_id"])
        self.assertEqual(sum(r["token"] is not None for r in results), 1)
        self.assertEqual(SourceReceipt.objects.count(), 1)
        self.assertEqual(Case.objects.count(), 1)

    def test_concurrent_followup_replay_appends_once(self):
        root = self.ingest()

        def attempt(_):
            connections.close_all()
            try:
                return self.ingest(f.telegram(2, parent=1), token=root["token"])
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(results[0]["receipt_id"], results[1]["receipt_id"])
        self.assertEqual(CaseEvidence.objects.count(), 2)

    def test_template_escapes_names_and_original_without_constructed_source_urls(self):
        data = json.loads(f.telegram())
        data["message"]["text"] = "<script>alert(1)</script>"
        data["message"]["from"]["first_name"] = "<img src=x>"
        root = self.ingest(f.raw(data))
        html = render_to_string(
            "source_case_intake/origins.html",
            {
                "source_origins": s.staff_origins(**self.staff(root)),
            },
        )
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)
        self.assertNotIn("<script>", html)
        self.assertIn('dir="rtl"', html)

    def test_populated_guard_reverse_reapply_preserves_receipt(self):
        root = self.ingest()
        try:
            MigrationExecutor(connection).migrate([("source_case_intake", "0001_initial")])
            self.assertEqual(
                bytes(SourceReceipt.objects.get(pk=root["receipt_id"]).raw), f.telegram()
            )
        finally:
            MigrationExecutor(connection).migrate([("source_case_intake", "0002_integrity_guards")])
        with self.assertRaises(IntegrityError), transaction.atomic():
            SourceReceipt.objects.filter(pk=root["receipt_id"]).update(sender="other")
