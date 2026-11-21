"""Administrative persistence contracts; native authorization is tested separately."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

from django.db import IntegrityError, close_old_connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent

from . import coordination, services
from .models import AssignmentEvent, PriorityEvent
from .tests import AssignmentFixture


@override_settings(FATWA_CASE_ASSIGNMENTS_ENABLED=True, FATWA_CASE_ASSIGNMENT_CANDIDATES=None)
class CoordinationPersistenceTests(AssignmentFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.organizer = replace(
            self.directory.identities["mufti-a"], subject_id="organizer", role="ORGANIZER"
        )
        self.directory.identities[self.organizer.subject_id] = self.organizer

    def assign(self, *, action="SET_PRIMARY", target="mufti-b", version=0, command=None, **changes):
        with transaction.atomic():
            case = Case.objects.select_for_update().get(pk=self.receipt["case_id"])
            values = dict(
                case=case,
                actor=self.organizer,
                provider_id=self.directory.provider_id,
                action=action,
                target_subject=target,
                target_actor=self.directory.resolve(target) if action == "SET_PRIMARY" else None,
                reason="توزيع بشري صريح على مفتي مخول أصلًا",
                command_id=command or uuid.uuid4(),
                expected_version=version,
                expected_revision=case.revision,
                expected_evidence_version=case.evidence_version,
            )
            return coordination._append_assignment_locked(**{**values, **changes})

    def priority(self, *, value="urgent", rank=0, version=0, command=None, **changes):
        with transaction.atomic():
            case = Case.objects.select_for_update().get(pk=self.receipt["case_id"])
            values = dict(
                case=case,
                actor=self.organizer,
                provider_id=self.directory.provider_id,
                value=value,
                rank=rank,
                label="أولوية اصطناعية محددة",
                policy_sha256="a" * 64,
                reason="سبب إداري بشري محفوظ",
                command_id=command or uuid.uuid4(),
                expected_version=version,
                expected_revision=case.revision,
                expected_evidence_version=case.evidence_version,
            )
            return coordination._append_priority_locked(**{**values, **changes})

    def test_real_organizer_assignment_preserves_source_and_old_mufti_workflow(self):
        approved = self.approved()
        source = list(CaseEvent.objects.values())
        original_identities = dict(self.directory.identities)
        row, created = self.assign()
        self.assertTrue(created)
        self.assertEqual(
            (row.subject_id, row.actor_role, row.target_subject),
            ("organizer", "ORGANIZER", "mufti-b"),
        )
        self.assertEqual(services.read_assignment(**self.common())["primary_subject"], "mufti-b")
        with override_settings(FATWA_CASE_ASSIGNMENT_CANDIDATES=lambda actor, ref: ["mufti-c"]):
            changed = self.change("TRANSFER", actor="mufti-b", target="mufti-c", version=1)
        self.assertEqual(changed["primary_subject"], "mufti-c")
        self.change("RELEASE", actor="mufti-c", version=2)
        self.assertTrue(services.read_assignment(**self.common())["is_shared"])
        self.assertEqual(cases.read_case(**self.common()), approved)
        self.assertEqual(list(CaseEvent.objects.values()), source)
        self.assertEqual(self.directory.identities, original_identities)

    def test_existing_mufti_api_cannot_accept_administrative_actions(self):
        for action in ("SET_PRIMARY", "CLEAR_PRIMARY"):
            with self.subTest(action=action), self.assertRaises(cases.CaseConflict):
                self.change(action, target="mufti-b")
        with self.assertRaises(cases.CaseConflict):
            cases.save_answer(
                **self.common("organizer"),
                text="لا يُسمح بهذا الجواب",
                expected_revision=1,
                expected_evidence_version=1,
            )
        self.assertFalse(AssignmentEvent.objects.exists())

    def test_administrative_clear_and_new_claim_keep_history_and_namespace(self):
        self.change("CLAIM")
        original = AssignmentEvent.objects.get()
        original_sha = original.sha256
        row, _ = self.assign(action="CLEAR_PRIMARY", target="mufti-a", version=1)
        self.assertEqual(row.reason, "توزيع بشري صريح على مفتي مخول أصلًا")
        self.change("CLAIM", actor="mufti-c", version=2)
        original.refresh_from_db()
        self.assertEqual(
            (original.sha256, original.actor_role, original.reason, original.command_id),
            (original_sha, "", "", None),
        )
        self.assertEqual(services.read_assignment(**self.common())["primary_subject"], "mufti-c")

    def test_exact_command_replay_after_later_event_is_one_write_and_reuse_denied(self):
        command = uuid.uuid4()
        first, _ = self.assign(command=command)
        self.assign(action="CLEAR_PRIMARY", target="mufti-b", version=1)
        replay, created = self.assign(command=command)
        self.assertEqual(first.pk, replay.pk)
        self.assertFalse(created)
        with self.assertRaises(cases.CaseConflict):
            self.assign(command=command, target="mufti-c")
        with self.assertRaises(cases.CaseConflict):
            self.assign(command=command, reason="سبب مختلف")
        self.assertEqual(AssignmentEvent.objects.count(), 2)

    def test_target_role_scope_and_versions_are_not_created_by_assignment(self):
        valid = self.directory.identities["mufti-b"]
        for target in (
            replace(valid, role="ORGANIZER"),
            replace(valid, active=False),
            replace(valid, case_keys=frozenset({"unrelated"})),
            None,
        ):
            with self.subTest(target=target), self.assertRaises(cases.CaseConflict):
                self.assign(target_actor=target)
        with self.assertRaises(cases.CaseConflict):
            self.assign(expected_revision=2)
        with self.assertRaises(cases.CaseConflict):
            self.assign(reason=" ")
        self.assertFalse(AssignmentEvent.objects.exists())

    def test_two_administrative_writers_share_canonical_compare_and_set(self):
        ready = Barrier(2)

        def write(target):
            close_old_connections()
            try:
                ready.wait(timeout=5)
                try:
                    self.assign(target=target)
                    return "accepted"
                except cases.CaseConflict:
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            observed = list(pool.map(write, ("mufti-b", "mufti-c")))
        self.assertCountEqual(observed, ["accepted", "conflict"])
        self.assertEqual(AssignmentEvent.objects.count(), 1)

    def test_sql_rejects_changed_admin_reason_role_and_illegal_clear(self):
        row, _ = self.assign()
        for changes in (
            {"reason": "changed"},
            {"actor_role": "MUFTI"},
            {"target_subject": "mufti-c"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                AssignmentEvent.objects.filter(pk=row.pk).update(**changes)
        for action, target in (("SET_PRIMARY", "mufti-b"), ("CLEAR_PRIMARY", "mufti-c")):
            candidate = AssignmentEvent(
                case_id=row.case_id,
                sequence=2,
                action=action,
                target_subject=target,
                subject_id="organizer",
                actor_role="ORGANIZER",
                provider_id=row.provider_id,
                auth_epoch="epoch-1",
                reason="سبب واضح",
                command_id=uuid.uuid4(),
                case_revision=row.case_revision,
                evidence_version=row.evidence_version,
                previous_sha256=row.sha256,
            )
            candidate.sha256 = services._digest(candidate)
            with (
                self.subTest(action=action),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                candidate.save(force_insert=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssignmentEvent.objects.filter(pk=row.pk).delete()

    def test_human_priority_reason_and_history_do_not_change_case(self):
        source = list(Case.objects.values()), list(CaseEvent.objects.values())
        command = uuid.uuid4()
        first, created = self.priority(command=command)
        self.assertTrue(created)
        second, _ = self.priority(value="normal", rank=20, version=1)
        replay, created = self.priority(command=command)
        self.assertEqual((replay.pk, created), (first.pk, False))
        state = coordination.priority_projection(
            coordination.priority_rows(
                Case.objects.get(pk=self.receipt["case_id"]), self.directory.provider_id
            )
        )
        self.assertEqual((state["version"], state["value"], state["rank"]), (2, "normal", 20))
        self.assertEqual(state["history"][0]["actor_role"], "ORGANIZER")
        self.assertEqual(second.previous_sha256, first.sha256)
        self.assertEqual((list(Case.objects.values()), list(CaseEvent.objects.values())), source)

    def test_priority_invalid_value_boolean_rank_stale_or_reused_command_denied(self):
        for changes in (
            {"value": ""},
            {"rank": True},
            {"rank": 101},
            {"reason": " "},
            {"label": "x\x00"},
            {"policy_sha256": "b" * 63},
            {"rank": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.priority(**changes)
        command = uuid.uuid4()
        self.priority(command=command)
        with self.assertRaises(cases.CaseConflict):
            self.priority(value="normal", rank=20)
        with self.assertRaises(cases.CaseConflict):
            self.priority(command=command, reason="غير السبب")
        with self.assertRaises(cases.CaseConflict):
            self.priority(version=1)
        self.assertEqual(PriorityEvent.objects.count(), 1)

    def test_priority_sql_history_and_digest_guard_reject_direct_mutations(self):
        first, _ = self.priority()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriorityEvent.objects.filter(pk=first.pk).update(reason="changed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriorityEvent.objects.filter(pk=first.pk).delete()
        values = {
            f.name: getattr(first, f.name)
            for f in PriorityEvent._meta.fields
            if f.name not in {"id", "transaction_id", "created_at"}
        }
        values.update(
            sequence=2,
            value="normal",
            rank=20,
            command_id=uuid.uuid4(),
            previous_sha256=first.sha256,
            sha256="0" * 64,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PriorityEvent.objects.create(**values)
        self.assertEqual(PriorityEvent.objects.count(), 1)
