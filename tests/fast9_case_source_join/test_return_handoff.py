"""Synthetic journal-to-return integration; every verifier here is test-only."""

import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from apps.delivery_planner.approval import ApprovalReceipt, CurrentEvidence
from apps.delivery_planner.outbox import (
    OutboxConflict,
    ProviderReceipt,
    list_intents,
    record_provider_receipt,
    reserve_for_adapter,
    stage_plan,
)
from apps.delivery_planner.outbox_recovery import (
    flag_expired_reservations,
    reconciliation_queue,
)
from apps.delivery_planner.planner import (
    Authority,
    Capabilities,
    Choice,
    InvalidPlan,
    plan_delivery,
)
from apps.delivery_planner.segmentation import parts_for_delivery
from apps.editorial_export.services import ExportError
from apps.fast9_case_source_join import return_handoff
from apps.fast9_case_source_join import source_journal as journal
from apps.fast9_case_source_join.answer_drafts import AUTHOR, CASE_KEY, REVIEWER
from apps.fast9_case_source_join.draft_source_review import inspect_draft_source
from apps.fast9_case_source_join.source_history import sample_source_events

TITLE = "  عنوانٌ تدريبي  "
BODY = "  محتوى اصطناعي لا يتضمن إفتاءً.\r\nالسطر الثاني\t  "
CONTENT_SHA256 = "99de76d59414059258ded3e1a19afb71a5977772baf65dbbb7c55782c289a0ef"


class ReturnHandoffTests(TestCase):
    def setUp(self):
        self.handoff = return_handoff
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)

    def snapshot(self):
        return journal.read_case_review(self.directory, synthetic_fixtures_only=True)

    def candidate(self):
        return self.handoff.read_return_candidate(self.directory, synthetic_fixtures_only=True)

    def current(self, case_key=CASE_KEY):
        return self.handoff.read_current_evidence(
            self.directory, case_key, synthetic_fixtures_only=True
        )

    def put(self, event):
        return journal.append_source_event(self.directory, event, synthetic_fixtures_only=True)

    def receive(self):
        self.put(sample_source_events(CASE_KEY, "received")[0])

    def reading_pins(self):
        snapshot = self.snapshot()
        observation = inspect_draft_source(
            CASE_KEY, 1, snapshot.events, synthetic_fixtures_only=True
        )
        return dict(
            reviewer=REVIEWER,
            count=len(snapshot.events),
            source_digest=journal.history_digest(snapshot.events),
            draft_digest=observation.draft_revision_sha256,
        )

    def read_source(self):
        return journal.acknowledge_review(
            self.directory,
            **self.reading_pins(),
            reply_digest=self.snapshot().reply_digest,
            synthetic_fixtures_only=True,
        )

    def request(self):
        return journal.record_clarification(
            self.directory,
            **self.reading_pins(),
            thread_digest=self.snapshot().thread_digest,
            kind="request",
            value="استيضاح اصطناعي للاختبار فقط",
            synthetic_fixtures_only=True,
        )

    def reply(self):
        snapshot = self.snapshot()
        code = journal.issue_reply_code(
            self.directory,
            **self.reading_pins(),
            thread_digest=snapshot.thread_digest,
            grant_revision=snapshot.grant_revision,
            synthetic_fixtures_only=True,
        ).code
        reply = journal.submit_requester_reply(
            self.directory, code, "تفصيل اصطناعي من السائل", synthetic_fixtures_only=True
        )
        with self.assertRaises(journal.ReplyCodeUnavailable):
            journal.submit_requester_reply(
                self.directory, code, "إعادة استخدام ممنوعة", synthetic_fixtures_only=True
            )
        return reply

    def draft(self, *, title=TITLE, body=BODY):
        snapshot = self.snapshot()
        return journal.save_answer_draft(
            self.directory,
            author=AUTHOR,
            base_revision=len(snapshot.drafts),
            count=len(snapshot.events),
            source_digest=journal.history_digest(snapshot.events),
            reply_digest=snapshot.reply_digest,
            title=title,
            body=body,
            evidence_seen=True,
            synthetic_fixtures_only=True,
        )

    def note(self, action):
        snapshot = self.snapshot()
        draft = snapshot.drafts[-1]
        return journal.record_draft_note(
            self.directory,
            reviewer=AUTHOR if action == "submit" else REVIEWER,
            action=action,
            text="تغيير اصطناعي مطلوب" if action == "request" else "",
            revision=draft.revision,
            draft_digest=draft.digest,
            note_count=len(snapshot.draft_notes),
            synthetic_fixtures_only=True,
        )

    def ready(self, *, clarification=False):
        self.receive()
        reading = self.read_source()
        if clarification:
            self.request()
            self.reply()
            reading = self.read_source()
        draft = self.draft()
        self.note("submit")
        self.note("confirm")
        return reading, draft

    def files(self):
        return {path.name: path.read_bytes() for path in self.directory.iterdir()}

    def assert_blocked(self, *blockers):
        candidate = self.candidate()
        self.assertEqual(candidate.blockers, blockers)
        with self.assertRaisesRegex(InvalidPlan, "^" + blockers[0] + "$"):
            self.current()
        return candidate

    def test_exact_human_content_and_fixed_intake_reading_are_distinct(self):
        reading, draft = self.ready(clarification=True)
        # Catch using AnswerDraft.digest as reading identity or as the answer content hash.
        self.assertNotEqual(reading.draft_digest, draft.digest)
        before = self.files()
        with patch.object(self.handoff, "read_case_review", wraps=journal.read_case_review) as read:
            candidate = self.candidate()
        self.assertEqual(read.call_count, 1)
        self.assertEqual(candidate.draft, draft)
        self.assertEqual((candidate.draft.title, candidate.draft.body), (TITLE, BODY))
        self.assertEqual(candidate.blockers, ())
        self.assertTrue(candidate.reading_current)
        self.assertTrue(candidate.technical_review_current)
        self.assertEqual(candidate.case_key, CASE_KEY)
        self.assertEqual(candidate.source_count, 1)
        self.assertEqual(
            (
                candidate.source_channel,
                candidate.source_account,
                candidate.source_conversation,
                candidate.source_reference,
            ),
            ("wave7-synthetic", "fixture-account-b", "fixture-thread-a", "fixture-msg-11"),
        )
        snapshot = self.snapshot()
        self.assertEqual(
            candidate.evidence,
            CurrentEvidence(
                CASE_KEY,
                1,
                CONTENT_SHA256,
                journal.history_digest(snapshot.events),
                snapshot.clarifications[-1].digest,
            ),
        )
        self.assertEqual(self.current(), candidate.evidence)
        self.assertEqual(self.candidate(), candidate)
        self.assertEqual(self.files(), before)

    def test_missing_content_does_not_create_files_or_dependent_blockers(self):
        candidate = self.assert_blocked("source_missing", "answer_missing")
        self.assertIsNone(candidate.draft)
        self.assertIsNone(candidate.evidence)
        self.assertIsNone(candidate.source_channel)
        self.assertEqual(candidate.source_count, 0)
        self.assertEqual(self.files(), {})
        self.receive()
        self.assert_blocked("answer_missing")

    def test_unread_answer_and_unconfirmed_answer_are_blocked(self):
        self.receive()
        self.draft()
        self.assert_blocked("source_reading_required", "technical_review_required")
        self.read_source()
        self.assert_blocked("technical_review_required")
        self.note("submit")
        self.assert_blocked("technical_review_required")
        self.note("confirm")
        self.assertEqual(self.candidate().blockers, ())

    def test_correction_then_deletion_invalidate_all_dependent_evidence(self):
        self.ready()
        self.put(sample_source_events(CASE_KEY, "corrected")[-1])
        candidate = self.assert_blocked(
            "answer_evidence_stale", "source_reading_required", "technical_review_required"
        )
        self.assertFalse(candidate.reading_current)
        self.assertFalse(candidate.technical_review_current)
        self.read_source()
        self.assert_blocked("answer_evidence_stale", "technical_review_required")
        self.put(sample_source_events(CASE_KEY, "deleted")[-1])
        candidate = self.assert_blocked(
            "source_deleted",
            "answer_evidence_stale",
            "source_reading_required",
            "technical_review_required",
        )
        self.assertTrue(candidate.evidence.source_deleted)

    def test_pending_request_uses_last_reply_not_thread_tip(self):
        self.ready(clarification=True)
        last_reply = self.snapshot().reply_digest
        self.request()
        candidate = self.assert_blocked("clarification_pending", "technical_review_required")
        self.assertEqual(candidate.evidence.reply_digest, last_reply)
        self.assertNotEqual(candidate.evidence.reply_digest, self.snapshot().thread_digest)
        self.assertTrue(candidate.reading_current)
        self.assertTrue(candidate.evidence.clarification_pending)
        self.reply()
        self.assert_blocked(
            "answer_evidence_stale", "source_reading_required", "technical_review_required"
        )

    def test_body_and_title_revisions_need_new_technical_confirmation(self):
        self.ready()
        previous = self.current()
        self.draft(title=TITLE + "معدل")
        candidate = self.assert_blocked("technical_review_required")
        self.assertTrue(candidate.reading_current)
        self.assertNotEqual(candidate.evidence.answer_sha256, previous.answer_sha256)
        self.note("submit")
        self.note("confirm")
        self.assertEqual(self.candidate().blockers, ())
        self.draft(title=TITLE + "معدل", body=BODY + "ملحق")
        self.assert_blocked("technical_review_required")

    def test_change_request_stays_open_until_explicit_resolution(self):
        self.ready()
        self.note("request")
        candidate = self.assert_blocked("change_request_open", "technical_review_required")
        self.assertTrue(candidate.evidence.change_request_open)
        self.draft(body=BODY + "تعديل")
        self.assert_blocked("change_request_open", "technical_review_required")
        self.note("close")
        self.assert_blocked("technical_review_required")
        self.note("submit")
        self.note("confirm")
        self.assertEqual(self.candidate().blockers, ())

    def test_wrong_case_guards_and_corrupt_storage_fail_closed(self):
        with self.assertRaisesRegex(InvalidPlan, "^return_case_mismatch$"):
            self.current("intake-1")
        with self.assertRaises(ExportError):
            self.handoff.read_return_candidate(self.directory)
        with self.assertRaises(ExportError):
            self.handoff.read_current_evidence(self.directory, CASE_KEY)
        for env in (
            {"FATWA_PRODUCTION": "1"},
            {"DJANGO_SETTINGS_MODULE": "config.settings.production"},
        ):
            with self.subTest(env=env), patch.dict(os.environ, env):
                with self.assertRaises(ExportError):
                    self.candidate()
                with self.assertRaises(ExportError):
                    self.current()
        self.assertEqual(self.files(), {})
        (self.directory / journal.JOURNAL_FILENAME).write_bytes(b"not a SQLite journal")
        before = self.files()
        with self.assertRaises(journal.JournalError):
            self.candidate()
        with self.assertRaises(journal.JournalError):
            self.current()
        self.assertEqual(self.files(), before)

    def test_unavailable_directory_is_not_missing_content(self):
        with self.assertRaises((journal.JournalError, OSError)):
            self.handoff.read_return_candidate(
                self.directory / "missing", synthetic_fixtures_only=True
            )

    def planned(self):
        candidate = self.candidate()
        evidence = candidate.evidence
        body = candidate.draft.body
        capabilities = Capabilities(
            candidate.source_channel, "test-only.v1", frozenset({"text"}), 30, True
        )
        parts, segments = parts_for_delivery(
            body, capabilities, explicit_human_choice=True
        )
        self.assertEqual("".join(segment.exact_text for segment in segments), body)
        self.assertEqual(len(parts), len(segments))
        for ordinal, (part, segment) in enumerate(zip(parts, segments, strict=True), 1):
            self.assertEqual(part.ordinal, ordinal)
            self.assertEqual(segment.ordinal, ordinal)
            self.assertEqual(part.media_type, "text")
            self.assertEqual(part.length, len(segment.exact_text))
            self.assertEqual(segment.length, part.length)
            self.assertLessEqual(part.length, capabilities.max_text_chars)
            self.assertEqual(part.sha256, sha256(segment.exact_text.encode()).hexdigest())
            self.assertEqual(segment.sha256, part.sha256)
        plan = plan_delivery(
            case_key=CASE_KEY,
            source_peer_key=candidate.source_conversation,
            parts=parts,
            capabilities=capabilities,
            authority=Authority(evidence.answer_revision, evidence.answer_sha256, True),
            choice=Choice(),
        )
        self.assertEqual(len(plan.steps), len(parts))
        # Test fixture only: production requires an independently trusted MUFTI verifier.
        approval = ApprovalReceipt(
            CASE_KEY,
            evidence.answer_revision,
            evidence.answer_sha256,
            evidence.source_digest,
            evidence.reply_digest,
            "test-only-mufti",
            "MUFTI",
            "APPROVE_RETURN_TO_ORIGIN",
            "test-only-receipt",
            datetime.now(UTC).isoformat(),
        )
        return dict(
            plan=plan,
            evidence=evidence,
            approval=approval,
            verify_approval=lambda receipt: receipt == approval,
            synthetic_fixtures_only=True,
        )

    def reserve(self, options, key):
        return reserve_for_adapter(
            self.directory, **options, intent_key=key, get_current_evidence=self.current
        )

    def provider_receipt(self, reservation, reported):
        proof = ProviderReceipt(reservation.intent_key, "test-message-1", reported, "test-proof-" + reported.lower())
        return record_provider_receipt(
            self.directory,
            reservation=reservation,
            receipt=proof,
            verify_provider_receipt=lambda receipt: receipt == proof,
            synthetic_fixtures_only=True,
        )

    def test_lossless_return_roundtrip_dedupes_and_distinguishes_delivery(self):
        self.ready(clarification=True)
        options = self.planned()
        staged = stage_plan(self.directory, **options)
        self.assertEqual([row.state for row in staged], ["STAGED"] * len(options["plan"].steps))
        self.assertCountEqual(list_intents(self.directory, synthetic_fixtures_only=True), staged)
        self.assertEqual(stage_plan(self.directory, **options), staged)
        claim = self.reserve(options, staged[0].intent_key)
        self.assertEqual(self.provider_receipt(claim, "ACCEPTED").state, "SENT_UNCONFIRMED")
        self.assertEqual(self.provider_receipt(claim, "DELIVERED").state, "DELIVERED")

    def test_source_correction_prevents_staged_intent_reservation(self):
        self.ready()
        options = self.planned()
        staged = stage_plan(self.directory, **options)
        self.put(sample_source_events(CASE_KEY, "corrected")[-1])
        with self.assertRaisesRegex(
            OutboxConflict, "current_evidence_reader_unavailable"
        ) as raised:
            self.reserve(options, staged[0].intent_key)
        self.assertIsInstance(raised.exception.__cause__, InvalidPlan)
        self.assertEqual(str(raised.exception.__cause__), "answer_evidence_stale")
        self.assertCountEqual(list_intents(self.directory, synthetic_fixtures_only=True), staged)

    def test_technical_staleness_cannot_bypass_current_evidence_booleans(self):
        self.ready()
        options = self.planned()
        staged = stage_plan(self.directory, **options)
        self.draft(title=TITLE + "جديد")
        with self.assertRaisesRegex(
            OutboxConflict, "current_evidence_reader_unavailable"
        ) as raised:
            self.reserve(options, staged[0].intent_key)
        self.assertEqual(str(raised.exception.__cause__), "technical_review_required")
        self.assertCountEqual(list_intents(self.directory, synthetic_fixtures_only=True), staged)

    def test_untrusted_or_unavailable_approval_creates_no_outbox(self):
        self.ready()
        options = self.planned()
        before = self.files()
        options["verify_approval"] = lambda receipt: False
        with self.assertRaisesRegex(InvalidPlan, "approval_signature_or_identity_not_verified"):
            stage_plan(self.directory, **options)
        self.assertEqual(self.files(), before)

        def unavailable(receipt):
            raise RuntimeError("test-only unavailable verifier")

        options["verify_approval"] = unavailable
        with self.assertRaisesRegex(InvalidPlan, "approval_verifier_unavailable"):
            stage_plan(self.directory, **options)
        self.assertEqual(self.files(), before)

    def test_expired_reservation_requires_reconciliation_before_late_delivery(self):
        self.ready()
        options = self.planned()
        staged = stage_plan(self.directory, **options)
        claim = self.reserve(options, staged[0].intent_key)
        after = datetime.fromisoformat(claim.until) + timedelta(seconds=1)
        queue = reconciliation_queue(self.directory, now=after, synthetic_fixtures_only=True)
        self.assertEqual(queue[0].attention, "UNCERTAIN_RESERVATION_EXPIRED")
        flagged = flag_expired_reservations(
            self.directory,
            operator_id="test-only-operator",
            verify_operator=lambda operator: operator == "test-only-operator",
            now=after,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(flagged, (claim.intent_key,))
        with self.assertRaisesRegex(OutboxConflict, "intent_not_reservable"):
            self.reserve(options, claim.intent_key)
        self.assertEqual(self.provider_receipt(claim, "DELIVERED").state, "DELIVERED")
