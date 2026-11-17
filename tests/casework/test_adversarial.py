"""Independent integrity and capability-race checks for the durable case boundary."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from apps.casework import services
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseEvent, CaseEvidence
from apps.delivery_queue import requester_tracking as legacy
from apps.delivery_queue.models import RequesterTrackingCase, RequesterTrackingToken
from apps.delivery_queue.requester_tracking import provision_tracking_case
from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider


class ScopedDirectory(MuftiIdentityProvider):
    """Test authority only, scoped to the exact generated public references."""

    provider_id = "independent-qa-directory"

    def __init__(self, references):
        self.references = frozenset(references)
        self.calls = 0
        self.change_epoch_at = None

    def authenticate(self, credential):
        return None

    def resolve(self, subject_id):
        self.calls += 1
        if subject_id != "qa-mufti":
            return None
        changed = self.change_epoch_at is not None and self.calls >= self.change_epoch_at
        return MuftiIdentity(
            "qa-mufti",
            "MUFTI",
            True,
            self.references,
            "epoch-new" if changed else "epoch-initial",
            timezone.now() + timedelta(minutes=20),
        )


class CaseworkAdversarialTests(TransactionTestCase):
    """Tests cross aggregate edges, not only the normal API call sequence."""

    def setUp(self):
        self.alpha = self.intake("alpha")
        self.beta = self.intake("beta")
        self.directory = ScopedDirectory([self.alpha["public_ref"], self.beta["public_ref"]])

    @staticmethod
    def intake(label):
        return services.intake_case(
            original_question=f"سؤال اصطناعي مستقل {label}",
            source_event_id=f"qa-source-{label}",
            requester_id=f"qa-requester-{label}",
            idempotency_key=f"qa-intake-{label}",
            synthetic_fixtures_only=True,
        )

    def staff_args(self, item):
        return {
            "case_id": item["case_id"],
            "subject_id": "qa-mufti",
            "provider": self.directory,
            "synthetic_fixtures_only": True,
        }

    def draft(self, item, text="جواب بشري اصطناعي"):
        return services.save_answer(
            **self.staff_args(item),
            text=text,
            expected_revision=item["revision"],
            expected_evidence_version=item["evidence_version"],
        )

    def test_answer_cannot_reference_missing_evidence_for_its_own_case(self):
        # The other case has evidence v2; that does not satisfy alpha's evidence FK.
        services.add_followup(
            token=self.beta["token"],
            text="إضافة إلى القضية الثانية فقط",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        text = "جواب لا يملك بينته في هذه القضية"
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnswerRevision.objects.create(
                case_id=self.alpha["case_id"],
                revision=1,
                evidence_version=2,
                text=text,
                text_sha256=sha256(text.encode()).hexdigest(),
                subject_id="qa-mufti",
                provider_id=self.directory.provider_id,
                auth_epoch="epoch-initial",
            )
        self.assertFalse(AnswerRevision.objects.filter(case_id=self.alpha["case_id"]).exists())

    def test_decision_rejects_another_cases_answer_in_api_and_database(self):
        alpha = self.draft(self.alpha, "جواب ألف")
        beta = self.draft(self.beta, "جواب باء")
        wrong_answer = beta["answers"][-1]["id"]
        with self.assertRaises(services.CaseConflict):
            services.record_decision(
                **self.staff_args(alpha),
                answer_id=wrong_answer,
                action="APPROVE",
                expected_revision=alpha["revision"],
                expected_evidence_version=alpha["evidence_version"],
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            CaseDecision.objects.create(
                case_id=alpha["case_id"],
                answer_id=wrong_answer,
                evidence_version=1,
                action="APPROVE",
                subject_id="qa-mufti",
                provider_id=self.directory.provider_id,
                auth_epoch="epoch-initial",
            )
        self.assertEqual(CaseDecision.objects.count(), 0)
        self.assertEqual(
            services.requester_status(self.alpha["token"], synthetic_fixtures_only=True)["status"],
            "UNDER_REVIEW",
        )

    def test_case_approved_answer_cannot_point_across_cases(self):
        alpha, beta = self.draft(self.alpha), self.draft(self.beta)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Case.objects.filter(pk=alpha["case_id"]).update(
                stage="ANSWERED",
                approved_answer_id=beta["answers"][-1]["id"],
                revision=alpha["revision"] + 1,
            )
        self.assertIsNone(Case.objects.get(pk=alpha["case_id"]).approved_answer_id)

    def test_foreign_answer_cannot_be_inserted_into_case_event_history(self):
        beta = self.draft(self.beta)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CaseEvent.objects.create(
                case_id=self.alpha["case_id"],
                sequence=2,
                action="ROTATE_ACCESS",
                stage="RECEIVED",
                evidence_version=1,
                answer_revision=0,
                subject_id="qa-mufti",
                answer_id=beta["answers"][-1]["id"],
            )
        self.assertEqual(CaseEvent.objects.filter(case_id=self.alpha["case_id"]).count(), 1)

    def test_case_cannot_commit_without_original_source_evidence_and_initial_event(self):
        case_id = uuid.uuid4()
        tracking_key = "case:" + str(case_id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            tracking = RequesterTrackingCase.objects.create(
                case_key=tracking_key,
                registered_by="qa-mufti",
            )
            Case.objects.create(
                id=case_id,
                public_ref="FT-2026-" + "A" * 20,
                requester_id="qa-orphan-requester",
                idempotency_key="qa-orphan-key",
                intake_sha256="a" * 64,
                tracking=tracking,
            )
        self.assertFalse(Case.objects.filter(pk=case_id).exists())
        self.assertFalse(RequesterTrackingCase.objects.filter(pk=tracking_key).exists())

    def test_existing_tracker_cannot_be_grafted_onto_durable_case(self):
        extra = RequesterTrackingCase.objects.create(
            case_key="qa-unbound-legacy-tracker",
            registered_by="qa-mufti",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Case.objects.filter(pk=self.alpha["case_id"]).update(tracking=extra, revision=2)
        self.assertEqual(
            Case.objects.get(pk=self.alpha["case_id"]).tracking_id, "case:" + self.alpha["case_id"]
        )

    def test_legacy_unbound_token_cannot_authorize_durable_case_api(self):
        token = provision_tracking_case(
            case_key="qa-legacy-only",
            operator_id="qa-operator",
            authorize_operator=lambda actor, target: True,
            expires_at=timezone.now() + timedelta(days=1),
        )
        with self.assertRaisesRegex(services.CaseConflict, "case_token_invalid_or_expired"):
            services.requester_status(token, synthetic_fixtures_only=True)
        with self.assertRaisesRegex(services.CaseConflict, "case_token_invalid_or_expired"):
            services.add_followup(
                token=token,
                text="محاولة ربط بلا قضية",
                expected_revision=1,
                synthetic_fixtures_only=True,
            )

    def test_mutation_cannot_disable_revision_preconditions_with_none_or_boolean(self):
        for field in ("expected_revision", "expected_evidence_version"):
            for invalid in (None, True, 0, "1"):
                with self.subTest(field=field, invalid=invalid):
                    versions = {"expected_revision": 1, "expected_evidence_version": 1}
                    versions[field] = invalid
                    with self.assertRaises(services.CaseConflict):
                        services.save_answer(
                            **self.staff_args(self.alpha), text="جواب غير معتمد", **versions
                        )
        self.assertEqual(AnswerRevision.objects.count(), 0)
        self.assertEqual(CaseEvent.objects.count(), 2)

    def test_identity_epoch_change_while_acquiring_case_lock_rolls_back_action(self):
        self.directory.calls = 0
        self.directory.change_epoch_at = 2
        with self.assertRaisesRegex(services.CaseConflict, "case_identity_changed"):
            self.draft(self.alpha)
        self.assertEqual(AnswerRevision.objects.count(), 0)
        self.assertEqual(Case.objects.get(pk=self.alpha["case_id"]).revision, 1)

    def test_current_snapshot_cannot_silently_diverge_from_append_only_history(self):
        # Either PostgreSQL rejects the write or the public projection rejects it.
        # In neither case may a forged stage be shown as a legitimate transition.
        try:
            with transaction.atomic():
                Case.objects.filter(pk=self.alpha["case_id"]).update(
                    stage="NEEDS_CLARIFICATION", revision=2
                )
        except IntegrityError:
            self.assertEqual(
                services.requester_status(self.alpha["token"], synthetic_fixtures_only=True)[
                    "status"
                ],
                "RECEIVED",
            )
        else:
            with self.assertRaises(services.CaseConflict):
                services.requester_status(self.alpha["token"], synthetic_fixtures_only=True)

    def test_revocation_committed_while_request_waits_for_lock_denies_followup(self):
        waiting = Event()
        digest = sha256(self.alpha["token"].encode()).hexdigest()

        def blocked_request():
            close_old_connections()

            def observe_lock(execute, sql, params, many, context):
                if "casework_case" in sql and "FOR UPDATE" in sql.upper():
                    waiting.set()
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(observe_lock):
                    services.add_followup(
                        token=self.alpha["token"],
                        text="لا يجوز حفظه بعد الإبطال",
                        expected_revision=1,
                        synthetic_fixtures_only=True,
                    )
                return "UNEXPECTED_WRITE"
            except services.CaseConflict as exc:
                return str(exc)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Case.objects.select_for_update().get(pk=self.alpha["case_id"])
                future = pool.submit(blocked_request)
                if not waiting.wait(timeout=10):
                    self.fail("requester did not reach case lock while revocation was staged")
                RequesterTrackingToken.objects.filter(pk=digest).update(revoked_at=timezone.now())
            self.assertEqual(future.result(timeout=10), "case_token_invalid_or_expired")
        self.assertEqual(CaseEvidence.objects.filter(case_id=self.alpha["case_id"]).count(), 1)
        self.assertEqual(CaseEvent.objects.filter(case_id=self.alpha["case_id"]).count(), 1)

    def test_legacy_rotation_queued_before_lookup_invalidates_waiting_lookup(self):
        case_key = "qa-legacy-rotation-race"
        old_token = provision_tracking_case(
            case_key=case_key,
            operator_id="qa-operator",
            authorize_operator=lambda *_: True,
            expires_at=timezone.now() + timedelta(days=1),
        )
        reached = {"rotate": Event(), "lookup": Event()}
        backend_pids = {}

        def operation(kind):
            close_old_connections()

            def observe_lock(execute, sql, params, many, context):
                if "fatwa_requester_tracking_case" in sql and "FOR UPDATE" in sql.upper():
                    backend_pids[kind] = connection.connection.info.backend_pid
                    reached[kind].set()
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(observe_lock):
                    if kind == "rotate":
                        return legacy.rotate_tracking_token(
                            case_key=case_key,
                            operator_id="qa-operator",
                            authorize_operator=lambda *_: True,
                            expires_at=timezone.now() + timedelta(days=1),
                        )
                    return legacy.lookup_case_status(old_token)
            except legacy.TrackingDenied as exc:
                return str(exc)
            finally:
                connections.close_all()

        def wait_for_real_lock(kind):
            self.assertTrue(reached[kind].wait(timeout=10), f"{kind} did not reach row lock")
            deadline = monotonic() + 10
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s",
                        [backend_pids[kind]],
                    )
                    row = cursor.fetchone()
                if row and row[0] == "Lock":
                    return
                sleep(0.01)
            self.fail(f"{kind} did not block on the held PostgreSQL row lock")

        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                RequesterTrackingCase.objects.select_for_update().get(pk=case_key)
                rotation = pool.submit(operation, "rotate")
                wait_for_real_lock("rotate")
                lookup = pool.submit(operation, "lookup")
                wait_for_real_lock("lookup")
            new_token = rotation.result(timeout=10)
            self.assertEqual(lookup.result(timeout=10), "tracking_token_invalid_or_expired")
        self.assertNotEqual(new_token, old_token)
        self.assertEqual(legacy.lookup_case_status(new_token)["status"], "RECEIVED")

    def test_core_journey_performs_no_python_network_connections(self):
        # psycopg uses libpq; keep the already established owned DB connection.
        connection.ensure_connection()
        with patch(
            "socket.socket.connect", side_effect=AssertionError("external send attempted")
        ) as connect:
            alpha = self.draft(self.alpha)
            alpha = services.record_decision(
                **self.staff_args(alpha),
                answer_id=alpha["answers"][-1]["id"],
                action="APPROVE",
                expected_revision=alpha["revision"],
                expected_evidence_version=alpha["evidence_version"],
            )
            services.add_followup(
                token=self.beta["token"],
                text="بيان اصطناعي إضافي",
                expected_revision=1,
                synthetic_fixtures_only=True,
            )
            result = services.requester_status(self.alpha["token"], synthetic_fixtures_only=True)
            self.assertEqual(result["status"], "ANSWERED")
            self.assertIs(result["delivery_verified"], False)
            self.assertIs(result["read_confirmed"], False)
            connect.assert_not_called()
