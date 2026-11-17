"""PostgreSQL contract tests for durable synthetic cases and immutable evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from unittest.mock import patch

from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from apps.casework import services as s
from apps.casework.models import (
    AnswerRevision,
    Case,
    CaseDecision,
    CaseEvent,
    CaseEvidence,
    CaseSource,
)
from apps.delivery_queue.models import RequesterTrackingCase, RequesterTrackingToken
from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider


class TestDirectory(MuftiIdentityProvider):
    provider_id = "synthetic-case-directory"

    def __init__(self, refs=(), role="MUFTI", epoch="epoch-1"):
        self.refs = frozenset(refs)
        self.role = role
        self.epoch = epoch

    def resolve(self, subject_id):
        if subject_id != "synthetic-mufti":
            return None
        return MuftiIdentity(
            subject_id,
            self.role,
            True,
            self.refs,
            self.epoch,
            timezone.now() + timedelta(minutes=30),
        )

    def authenticate(self, credential):
        return (
            self.resolve("synthetic-mufti")
            if credential == "synthetic-credential-with-32-characters"
            else None
        )


class DurableCaseTests(TransactionTestCase):
    def intake(self, suffix="a", text="  سؤال اصطناعي\nكما ورد حرفيًا.  ", **kwargs):
        args = dict(
            original_question=text,
            source_event_id="website:" + suffix,
            requester_id="requester-" + suffix,
            idempotency_key="intake-" + suffix,
            synthetic_fixtures_only=True,
        )
        args.update(kwargs)
        return s.intake_case(**args)

    def staff(self, receipt, directory=None, **kwargs):
        result = dict(
            case_id=receipt["case_id"],
            subject_id="synthetic-mufti",
            provider=directory or TestDirectory([receipt["public_ref"]]),
            synthetic_fixtures_only=True,
        )
        result.update(kwargs)
        return result

    def draft(self, receipt, **kwargs):
        args = self.staff(
            receipt,
            expected_revision=receipt["revision"],
            expected_evidence_version=receipt["evidence_version"],
            text="جواب بشري اصطناعي للاختبار.",
        )
        args.update(kwargs)
        return s.save_answer(**args)

    def approve(self, receipt):
        return s.record_decision(
            **self.staff(receipt),
            answer_id=receipt["answers"][-1]["id"],
            expected_revision=receipt["revision"],
            expected_evidence_version=receipt["evidence_version"],
            action="APPROVE",
        )

    def test_two_cases_have_distinct_durable_identity_and_lossless_original(self):
        a, b = self.intake("a"), self.intake("b")
        self.assertNotEqual(a["case_id"], b["case_id"])
        self.assertNotEqual(a["public_ref"], b["public_ref"])
        self.assertNotEqual(a["case_id"], a["public_ref"])
        self.assertEqual(Case.objects.count(), 2)
        self.assertEqual(CaseSource.objects.count(), 2)
        self.assertEqual(RequesterTrackingCase.objects.count(), 2)
        self.assertEqual(
            s.read_case(**self.staff(a))["original_question"], "  سؤال اصطناعي\nكما ورد حرفيًا.  "
        )
        public = s.requester_status(a["token"], synthetic_fixtures_only=True)
        self.assertNotIn("case_id", public)
        self.assertNotIn("original_question", public)
        self.assertNotIn(b["public_ref"], str(public))

    def test_duplicate_intake_is_idempotent_and_does_not_reissue_secret(self):
        first, again = self.intake(), self.intake()
        self.assertEqual(first["case_id"], again["case_id"])
        self.assertFalse(again["created"])
        self.assertIsNone(again["token"])
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(CaseEvent.objects.count(), 1)
        self.assertEqual(RequesterTrackingToken.objects.count(), 1)

    def test_duplicate_key_with_changed_content_or_source_is_denied(self):
        self.intake()
        for kwargs in ({"text": "متن آخر"}, {"source_event_id": "website:changed"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(s.CaseConflict):
                self.intake(**kwargs)
        with self.assertRaisesRegex(s.CaseConflict, "source_event_already_recorded"):
            self.intake("other", source_event_id="website:a")
        self.assertEqual(Case.objects.count(), 1)

    def test_original_and_versioned_evidence_cannot_be_mutated_or_deleted(self):
        a = self.intake()
        for model, field, value in (
            (CaseSource, "original_question", "changed"),
            (CaseEvidence, "text", "changed"),
        ):
            with self.subTest(model=model), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.filter(case_id=a["case_id"]).update(**{field: value})
        self.assertEqual(
            s.read_case(**self.staff(a))["original_question"], "  سؤال اصطناعي\nكما ورد حرفيًا.  "
        )

    def test_mufti_answer_and_approval_bound_to_exact_evidence(self):
        a = self.intake()
        draft = self.draft(a)
        approved = self.approve(draft)
        self.assertEqual(approved["status"], "ANSWERED")
        self.assertEqual(approved["approved_answer_id"], draft["answers"][0]["id"])
        public = s.requester_status(a["token"], synthetic_fixtures_only=True)
        self.assertEqual(public["status"], "ANSWERED")
        self.assertFalse(public["delivery_verified"])
        self.assertFalse(public["read_confirmed"])
        self.assertEqual(CaseDecision.objects.count(), 1)

    def test_followup_invalidates_previous_approval_without_erasing_history(self):
        a = self.intake()
        approved = self.approve(self.draft(a))
        followup = s.add_followup(
            token=a["token"],
            text="تفصيل جديد",
            expected_revision=approved["revision"],
            synthetic_fixtures_only=True,
        )
        current = s.read_case(**self.staff(a))
        self.assertEqual(followup["status"], "UNDER_REVIEW")
        self.assertEqual(current["evidence_version"], 2)
        self.assertIsNone(current["approved_answer_id"])
        self.assertEqual(current["original_question"], "  سؤال اصطناعي\nكما ورد حرفيًا.  ")
        self.assertEqual(CaseDecision.objects.count(), 1)
        with self.assertRaisesRegex(s.CaseConflict, "current_answer_required"):
            s.record_decision(
                **self.staff(a),
                answer_id=approved["answers"][0]["id"],
                expected_revision=current["revision"],
                expected_evidence_version=2,
                action="APPROVE",
            )

    def test_clarification_returns_same_case_then_new_human_version_is_required(self):
        a = self.intake()
        clarification = s.request_clarification(
            **self.staff(a),
            text="أضف التفصيل الاصطناعي",
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.assertEqual(
            s.requester_status(a["token"], synthetic_fixtures_only=True)["clarification"],
            "أضف التفصيل الاصطناعي",
        )
        followup = s.add_followup(
            token=a["token"],
            text="تفصيل",
            expected_revision=clarification["revision"],
            synthetic_fixtures_only=True,
        )
        self.assertEqual(followup["public_ref"], a["public_ref"])
        current = s.read_case(**self.staff(a))
        approved = self.approve(self.draft(current))
        self.assertEqual(approved["status"], "ANSWERED")
        self.assertEqual(approved["evidence_version"], 2)
        self.assertEqual(Case.objects.count(), 1)

    def test_organizer_and_foreign_case_cannot_read_or_author_ruling(self):
        a, b = self.intake("a"), self.intake("b")
        for directory in (
            TestDirectory([a["public_ref"]], role="ORGANIZER_ADMIN"),
            TestDirectory([b["public_ref"]]),
        ):
            with (
                self.subTest(directory=directory),
                self.assertRaisesRegex(s.CaseConflict, "case_access_denied"),
            ):
                self.draft(a, provider=directory)
            with self.assertRaises(s.CaseConflict):
                s.read_case(**self.staff(a, directory))
        self.assertEqual(AnswerRevision.objects.count(), 0)
        self.assertEqual(
            len(
                s.list_cases(
                    subject_id="synthetic-mufti",
                    provider=TestDirectory([a["public_ref"]]),
                    synthetic_fixtures_only=True,
                )
            ),
            1,
        )

    def test_stale_versions_and_cross_case_answer_are_rejected(self):
        a, b = self.intake("a"), self.intake("b")
        da, db = self.draft(a), self.draft(b)
        with self.assertRaisesRegex(s.CaseConflict, "case_revision_changed"):
            self.draft(a)
        with self.assertRaisesRegex(s.CaseConflict, "case_evidence_changed"):
            self.draft(da, expected_evidence_version=2)
        with self.assertRaisesRegex(s.CaseConflict, "current_answer_required"):
            s.record_decision(
                **self.staff(a),
                answer_id=db["answers"][0]["id"],
                expected_revision=da["revision"],
                expected_evidence_version=1,
                action="APPROVE",
            )
        self.assertEqual(CaseDecision.objects.count(), 0)

    def test_return_for_changes_preserves_old_answer_and_requires_new_revision(self):
        a = self.intake()
        draft = self.draft(a)
        returned = s.record_decision(
            **self.staff(a),
            answer_id=draft["answers"][0]["id"],
            action="RETURN_FOR_CHANGES",
            note="ملاحظة بشرية",
            expected_revision=draft["revision"],
            expected_evidence_version=1,
        )
        self.assertEqual(returned["status"], "RETURNED_FOR_CHANGES")
        with self.assertRaisesRegex(s.CaseConflict, "answer_already_decided"):
            self.approve(returned)
        revised = self.draft(returned)
        self.assertEqual(len(revised["answers"]), 2)
        self.assertEqual(self.approve(revised)["status"], "ANSWERED")

    def test_revocation_and_trusted_recovery_do_not_accept_old_capability(self):
        a = self.intake()
        with self.assertRaisesRegex(s.CaseConflict, "requester_recovery_identity_mismatch"):
            s.rotate_access(**self.staff(a), requester_id="wrong-owner")
        rotated = s.rotate_access(**self.staff(a), requester_id="requester-a")
        self.assertNotEqual(rotated["token"], a["token"])
        with self.assertRaisesRegex(s.CaseConflict, "case_token_invalid_or_expired"):
            s.requester_status(a["token"], synthetic_fixtures_only=True)
        self.assertEqual(
            s.requester_status(rotated["token"], synthetic_fixtures_only=True)["public_ref"],
            a["public_ref"],
        )
        s.revoke_access(**self.staff(a), requester_id="requester-a")
        with self.assertRaises(s.CaseConflict):
            s.add_followup(
                token=rotated["token"],
                text="تفصيل",
                expected_revision=rotated["revision"],
                synthetic_fixtures_only=True,
            )
        self.assertEqual(RequesterTrackingToken.objects.filter(revoked_at__isnull=True).count(), 0)

    def test_tokens_are_hashed_and_invalid_or_expired_tokens_denied(self):
        a = self.intake()
        self.assertEqual(
            RequesterTrackingToken.objects.get().pk, sha256(a["token"].encode()).hexdigest()
        )
        for token in ("", None, True, "rt_" + "x" * 43, a["public_ref"]):
            with self.subTest(token=token), self.assertRaises(s.CaseConflict):
                s.requester_status(token, synthetic_fixtures_only=True)
        with (
            patch.object(s.timezone, "now", return_value=timezone.now() + timedelta(days=8)),
            self.assertRaises(s.CaseConflict),
        ):
            s.requester_status(a["token"], synthetic_fixtures_only=True)

    def test_intake_rollback_leaves_no_orphan_tracking_source_or_token(self):
        with patch.object(
            s.CaseEvent.objects, "create", side_effect=RuntimeError("synthetic-injected-fault")
        ):
            with self.assertRaises(RuntimeError):
                self.intake()
        for model in (
            Case,
            CaseSource,
            CaseEvidence,
            CaseEvent,
            RequesterTrackingCase,
            RequesterTrackingToken,
        ):
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def test_approval_rollback_preserves_unapproved_answer(self):
        a = self.intake()
        draft = self.draft(a)
        with patch.object(
            s.CaseEvent.objects, "create", side_effect=RuntimeError("synthetic-injected-fault")
        ):
            with self.assertRaises(RuntimeError):
                self.approve(draft)
        self.assertEqual(CaseDecision.objects.count(), 0)
        self.assertIsNone(s.read_case(**self.staff(a))["approved_answer_id"])
        self.assertEqual(self.approve(draft)["status"], "ANSWERED")

    def test_concurrent_duplicate_intake_creates_exactly_one_case(self):
        def create(_):
            connections.close_all()
            try:
                return self.intake("race")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))
        self.assertEqual({r["case_id"] for r in results}, {results[0]["case_id"]})
        self.assertEqual(sum(r["created"] for r in results), 1)
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(RequesterTrackingToken.objects.count(), 1)

    def test_two_full_concurrent_journeys_remain_independent(self):
        def journey(suffix):
            connections.close_all()
            try:
                case = self.intake(suffix)
                draft = self.draft(case)
                decision = self.approve(draft)
                return case, decision
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(journey, ["parallel-a", "parallel-b"]))
        self.assertEqual(Case.objects.count(), 2)
        self.assertEqual(CaseDecision.objects.count(), 2)
        for receipt, decision in results:
            self.assertEqual(decision["status"], "ANSWERED")
            self.assertEqual(
                s.requester_status(receipt["token"], synthetic_fixtures_only=True)["public_ref"],
                receipt["public_ref"],
            )

    def test_concurrent_same_revision_only_one_human_draft_commits(self):
        a = self.intake()

        def draft(_):
            connections.close_all()
            try:
                return self.draft(a)["status"]
            except s.CaseConflict as exc:
                return str(exc)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(draft, range(2)))
        self.assertCountEqual(results, ["UNDER_REVIEW", "case_revision_changed"])
        self.assertEqual(AnswerRevision.objects.count(), 1)

    def test_synthetic_ack_is_required_before_db_reads_or_writes(self):
        with self.assertRaisesRegex(s.CaseConflict, "synthetic_ack_required"):
            self.intake(synthetic_fixtures_only=False)
        self.assertEqual(Case.objects.count(), 0)

    def test_orphan_same_case_decision_cannot_block_valid_approval(self):
        a = self.intake()
        draft = self.draft(a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CaseDecision.objects.create(
                case_id=a["case_id"],
                answer_id=draft["answers"][0]["id"],
                evidence_version=1,
                action="APPROVE",
                subject_id="synthetic-mufti",
                provider_id="synthetic-case-directory",
                auth_epoch="epoch-1",
            )
        self.assertEqual(CaseDecision.objects.count(), 0)
        self.assertEqual(self.approve(draft)["status"], "ANSWERED")
