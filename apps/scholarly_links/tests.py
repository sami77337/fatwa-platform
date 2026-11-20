"""Real PostgreSQL evidence for lesson versions, manual links and native filters."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from threading import Barrier, Event
from unittest.mock import patch
from urllib.parse import urlencode

from django.conf import settings
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as answer_media
from apps.answer_media.models import AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.case_assignments.tests import Directory
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent
from apps.mufti_review.identity import IdentityUnavailable
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from . import services, views
from .authority import ScholarlyAuthority
from .models import (
    CaseLessonLink,
    CaseRelation,
    Lesson,
    LessonCategory,
    LessonSeries,
    LessonVersion,
    LinkDecision,
    SeriesVersion,
)

FEATURES = {"FATWA_SCHOLARLY_LINKS_ENABLED": True, "FATWA_ANSWER_MEDIA_ENABLED": True}


class Authority(ScholarlyAuthority):
    def __init__(self, refs):
        self.refs = set(refs)
        self.denied = set()
        self.epoch = "authority-1"

    def projection_epoch(self):
        return self.epoch

    def permits(self, **kw):
        return (
            kw["case_ref"] in self.refs
            and kw["target_case_ref"] in self.refs
            and kw["provider_id"] == Directory.provider_id
            and kw["auth_epoch"] == "epoch-1"
            and kw["subject_id"] in {"mufti-a", "mufti-b", "mufti-c"}
            and (kw["action"], kw["kind"]) not in self.denied
            and (kw["action"], kw["resource_id"]) not in self.denied
        )

    def revoke(self, action, kind):
        self.denied.add((action, kind))
        self.epoch += ".next"


class Fixture:
    def setUp(self):
        super().setUp()
        self.receipts = [
            cases.intake_case(
                original_question=f"سؤال اصطناعي مستقل {name} PRIVATE-QUESTION",
                requester_id="scholarly-requester-" + name,
                source_event_id="scholarly-event-" + name,
                idempotency_key="scholarly-key-" + name,
                synthetic_fixtures_only=True,
            )
            for name in ("alpha", "beta", "gamma")
        ]
        self.receipt = self.receipts[0]
        self.directory = Directory([row["public_ref"] for row in self.receipts])
        self.authority = Authority([row["public_ref"] for row in self.receipts])
        self.policies = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_SCHOLARLY_LINKS_AUTHORITY=self.authority,
        )
        self.policies.enable()
        self.addCleanup(self.policies.disable)
        for index, receipt in enumerate(self.receipts):
            common = self.common(receipt)
            if index == 0:
                answer_media.save_multipart_answer(
                    **common,
                    **self.pins(receipt),
                    text="جواب بشري اصطناعي alpha",
                    files=[audio_fixture()],
                )
            else:
                cases.save_answer(
                    **common, **self.pins(receipt), text="جواب بشري اصطناعي " + str(index)
                )
            answer = AnswerRevision.objects.filter(case_id=receipt["case_id"]).latest("revision")
            cases.record_decision(
                **common,
                **self.pins(receipt),
                answer_id=answer.pk,
                action="APPROVE",
                note="اعتماد اصطناعي صريح",
            )
        self.part = AnswerPart.objects.get(
            manifest__answer__case_id=self.receipt["case_id"], ordinal=2
        )

    def common(self, receipt=None, actor="mufti-a"):
        return dict(
            case_id=(receipt or self.receipt)["case_id"],
            subject_id=actor,
            provider=self.directory,
            synthetic_fixtures_only=True,
        )

    def pins(self, receipt=None):
        row = Case.objects.get(pk=(receipt or self.receipt)["case_id"])
        return dict(expected_revision=row.revision, expected_evidence_version=row.evidence_version)

    def category(self, label="دروس تعليمية", **changes):
        return services.create_category(
            **self.common(), **self.pins(), label=label, command_id=uuid.uuid4(), **changes
        )

    def series(self, **changes):
        values = dict(
            title="سلسلة اصطناعية موثقة",
            teachers=[
                {
                    "name": "معلم اصطناعي",
                    "provider_id": self.directory.provider_id,
                    "subject_id": "mufti-a",
                }
            ],
            command_id=uuid.uuid4(),
        )
        return services.save_series(**self.common(), **self.pins(), **{**values, **changes})

    def lesson(self, series=None, category=None, **changes):
        series, category = series or self.series(), category or self.category()
        series = SeriesVersion.objects.filter(series=series.series).latest("number")
        values = dict(
            series_id=series.series_id,
            expected_series_version=series.number,
            title="الدرس الأول الاصطناعي",
            category_id=category.pk,
            provenance="نسبة بشرية صريحة إلى ملف الجواب الاصطناعي",
            source_part_id=self.part.pk,
            command_id=uuid.uuid4(),
        )
        return services.save_lesson(**self.common(), **self.pins(), **{**values, **changes})

    def relation(self, kind="REFERRED_BY_SHEIKH", source=0, target=1, **changes):
        target_case = Case.objects.get(pk=self.receipts[target]["case_id"])
        values = dict(
            target_case_id=target_case.pk,
            target_answer_id=target_case.approved_answer_id,
            expected_target_revision=target_case.revision,
            expected_target_evidence_version=target_case.evidence_version,
            kind=kind,
            reason="إحالة بشرية صريحة للاختبار",
            command_id=uuid.uuid4(),
        )
        return services.propose_relation(
            **self.common(self.receipts[source]),
            **self.pins(self.receipts[source]),
            **{**values, **changes},
        )

    def link(self, version=None, source=0, **changes):
        version = version or self.lesson()
        owner = Case.objects.get(pk=version.lesson.series.case_id)
        values = dict(
            lesson_version_id=version.pk,
            expected_target_revision=owner.revision,
            expected_target_evidence_version=owner.evidence_version,
            reason="هذا الموضع يتناول المسألة حسب المراجعة البشرية",
            command_id=uuid.uuid4(),
            start_ms=10,
            end_ms=50,
        )
        return services.propose_lesson_link(
            **self.common(self.receipts[source]),
            **self.pins(self.receipts[source]),
            **{**values, **changes},
        )

    def review(self, row, action="APPROVE", **changes):
        source_id, target_id, _ = services._endpoints(row)
        target = Case.objects.get(pk=target_id)
        receipt = next(item for item in self.receipts if str(item["case_id"]) == str(source_id))
        values = dict(
            link_id=row.pk,
            link_kind="RELATION" if isinstance(row, CaseRelation) else "LESSON",
            action=action,
            note="قرار مراجعة بشرية اصطناعية",
            command_id=uuid.uuid4(),
            expected_sequence=row.decisions.count(),
            expected_target_revision=target.revision,
            expected_target_evidence_version=target.evidence_version,
        )
        return services.review_link(
            **self.common(receipt), **self.pins(receipt), **{**values, **changes}
        )

    def search(self, **changes):
        return services.search(
            subject_id="mufti-a", provider=self.directory, synthetic_fixtures_only=True, **changes
        )

    def snapshot(self):
        return [cases.read_case(**self.common(receipt)) for receipt in self.receipts]


@override_settings(**FEATURES)
class ServiceTests(Fixture, TransactionTestCase):
    def test_default_closed_authority_required_and_explicit_synthetic_guard(self):
        with (
            override_settings(FATWA_SCHOLARLY_LINKS_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.series()
        with (
            override_settings(FATWA_SCHOLARLY_LINKS_AUTHORITY=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.series()
        with self.assertRaises(cases.CaseConflict):
            services.desk(**{**self.common(), "synthetic_fixtures_only": False})
        self.assertEqual(LessonSeries.objects.count(), 0)

    def test_series_lessons_separate_classification_and_multiple_links_preserve_all_originals(self):
        before, events = self.snapshot(), CaseEvent.objects.count()
        category, series = self.category(), self.series()
        first = self.lesson(series, category)
        second = self.lesson(
            series,
            category,
            title="الدرس الثاني",
            source_part_id=None,
            provenance="مرجع وصفي بشري؛ الملف غير متاح",
        )
        first_link, second_link = self.link(first), self.link(second, start_ms=None, end_ms=None)
        self.assertEqual(self.search(lesson_id=str(first.lesson_id))["total"], 0)
        self.review(first_link)
        self.review(second_link)
        result = services.desk(**self.common())
        self.assertEqual([row["state"] for row in result["lesson_links"]], ["APPROVE", "APPROVE"])
        self.assertEqual(result["own_series"][0]["lessons"][1]["source_available"], False)
        self.assertNotEqual(first.lesson_id, second.lesson_id)
        self.assertNotEqual(first.lesson.public_id, first.lesson_id)
        self.assertEqual(LessonCategory._meta.get_field("case").remote_field.model, Case)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(CaseEvent.objects.count(), events)

    def test_reorder_is_versioned_without_changing_lesson_identity_or_pinned_link(self):
        category, series = self.category(), self.series()
        first, second = self.lesson(series, category), self.lesson(series, category, title="ثان")
        link = self.link(first)
        self.review(link)
        current = SeriesVersion.objects.filter(series=series.series).latest("number")
        moved = services.move_lesson(
            **self.common(),
            **self.pins(),
            series_id=series.series_id,
            lesson_id=second.lesson_id,
            direction="up",
            expected_series_version=current.number,
            command_id=uuid.uuid4(),
        )
        self.assertEqual(moved.lesson_order, [str(second.lesson_id), str(first.lesson_id)])
        self.assertEqual(
            SeriesVersion.objects.get(pk=current.pk).lesson_order,
            [str(first.lesson_id), str(second.lesson_id)],
        )
        link.refresh_from_db()
        self.assertEqual(link.lesson_version_id, first.pk)
        self.assertEqual(
            services.desk(**self.common())["lesson_links"][0]["lesson"]["version_id"], str(first.pk)
        )

    def test_lesson_new_recording_keeps_historical_source_and_time_pins(self):
        version = self.lesson()
        link = self.link(version)
        self.review(link)
        answer_media.save_multipart_answer(
            **self.common(),
            **self.pins(),
            text="جواب محفوظ أحدث",
            files=[{**audio_fixture(), "filename": "replacement.wav"}],
        )
        replacement = AnswerPart.objects.filter(
            manifest__answer__case_id=self.receipt["case_id"], ordinal=2
        ).latest("created_at")
        current_series = SeriesVersion.objects.filter(series=version.lesson.series).latest("number")
        newer = services.save_lesson(
            **self.common(),
            **self.pins(),
            series_id=version.lesson.series_id,
            expected_series_version=current_series.number,
            lesson_id=version.lesson_id,
            expected_lesson_version=1,
            title="نسخة جديدة من الدرس",
            category_id=version.category_id,
            provenance="تسجيل آخر اختير صراحة",
            source_part_id=replacement.pk,
            command_id=uuid.uuid4(),
        )
        self.assertNotEqual(newer.source_snapshot["part_id"], version.source_snapshot["part_id"])
        self.assertEqual(newer.number, 2)
        old = services.read_lesson(**self.common(), lesson_version_id=version.pk)
        self.assertEqual(old["source"]["part_id"], str(self.part.pk))
        link.refresh_from_db()
        self.assertEqual((link.lesson_version_id, link.start_ms, link.end_ms), (version.pk, 10, 50))
        self.assertEqual(
            services.open_lesson_media(**self.common(), lesson_version_id=version.pk)["raw"],
            audio_fixture()["raw"],
        )

    def test_optional_descriptive_source_and_exact_timing_validation(self):
        version = self.lesson(source_part_id=None)
        self.assertFalse(
            services.read_lesson(**self.common(), lesson_version_id=version.pk)["source_available"]
        )
        with self.assertRaises(cases.CaseConflict):
            self.link(version)
        link = self.link(version, start_ms=None, end_ms=None)
        self.assertIsNone(link.start_ms)
        with self.assertRaises(cases.CaseConflict):
            services.open_lesson_media(**self.common(), lesson_version_id=version.pk)
        with self.assertRaises(cases.CaseConflict):
            self.link(version, start_ms=None, end_ms=50)

    def test_all_four_typed_relations_preserve_direction_and_need_explicit_review(self):
        before = self.snapshot()
        rows = [self.relation(kind) for kind in services.KINDS]
        for row in rows:
            self.assertEqual(self.search(relation_kind=row.kind)["total"], 0)
            self.review(row)
            self.assertEqual(self.search(relation_kind=row.kind)["total"], 2)
        outgoing = services.desk(**self.common())["relations"]
        incoming = services.desk(**self.common(self.receipts[1]))["relations"]
        self.assertTrue(all(row["outgoing"] for row in outgoing))
        self.assertTrue(all(not row["outgoing"] for row in incoming))
        self.assertEqual({row["kind"] for row in incoming}, set(services.KINDS))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(Case.objects.count(), 3)

    def test_sensitive_review_does_not_follow_from_propose_or_read_permission(self):
        row = self.relation("SUPERSEDES")
        self.authority.revoke("APPROVE", "SUPERSEDES")
        with self.assertRaisesMessage(cases.CaseConflict, "scholarly_action_denied"):
            self.review(row)
        result = services.desk(**self.common())
        self.assertFalse(result["relations"][0]["can_approve"])
        self.assertEqual(row.decisions.count(), 0)

    def test_reject_withdraw_and_reproposal_keep_full_immutable_history(self):
        rejected = self.relation()
        self.review(rejected, "REJECT")
        approved = self.relation()
        self.review(approved)
        self.assertEqual(self.search(relation_kind=approved.kind)["total"], 2)
        self.review(approved, "WITHDRAW")
        self.assertEqual(self.search(relation_kind=approved.kind)["total"], 0)
        next_proposal = self.relation()
        self.assertEqual(services._status(next_proposal)[0], "PROPOSED")
        self.assertEqual(
            list(approved.decisions.order_by("sequence").values_list("action", flat=True)),
            ["APPROVE", "WITHDRAW"],
        )

    def test_self_duplicate_unknown_kind_and_unapproved_target_are_rejected(self):
        self.relation()
        with self.assertRaises(cases.CaseConflict):
            self.relation()
        with self.assertRaises(cases.CaseConflict):
            self.relation(source=0, target=0)
        with self.assertRaises(cases.CaseConflict):
            self.relation("AUTO_EQUIVALENT")
        target = self.receipts[1]
        draft = cases.save_answer(
            **self.common(target), **self.pins(target), text="مسودة جديدة غير معتمدة"
        )
        with self.assertRaises(cases.CaseConflict):
            self.relation(target_answer_id=draft["answers"][-1]["id"])
        self.assertEqual(CaseRelation.objects.count(), 1)

    def test_directional_three_case_cycle_is_rejected_without_record_merge(self):
        first = self.relation("SUPERSEDES", 0, 1)
        second = self.relation("SUPERSEDES", 1, 2)
        last = self.relation("SUPERSEDES", 2, 0)
        self.review(first)
        self.review(second)
        with self.assertRaises(cases.CaseConflict):
            self.review(last)
        self.assertEqual(last.decisions.count(), 0)
        self.assertEqual(Case.objects.count(), 3)

    def test_exact_command_retry_is_idempotent_and_changed_payload_is_rejected(self):
        command = uuid.uuid4()
        first = self.relation(command_id=command)
        retry = self.relation(command_id=command)
        self.assertEqual(first.pk, retry.pk)
        with self.assertRaises(cases.CaseConflict):
            self.relation(command_id=command, reason="تبديل المقصود بنفس المفتاح")
        command = uuid.uuid4()
        approved = self.review(first, command_id=command)
        self.assertEqual(self.review(first, command_id=command).pk, approved.pk)
        self.assertEqual(LinkDecision.objects.count(), 1)

    def test_stale_case_target_series_and_lesson_pins_do_not_write(self):
        series = self.series()
        self.series(series_id=series.series_id, expected_series_version=1, title="عنوان أحدث")
        with self.assertRaises(cases.CaseConflict):
            self.series(series_id=series.series_id, expected_series_version=1, title="عنوان قديم")
        target = self.receipts[1]
        old = self.pins(target)
        cases.add_followup(
            token=target["token"],
            text="تعقيب جديد",
            expected_revision=old["expected_revision"],
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.relation(
                expected_target_revision=old["expected_revision"],
                expected_target_evidence_version=old["expected_evidence_version"],
            )
        self.assertEqual(CaseRelation.objects.count(), 0)

    def test_teacher_identity_is_explicit_and_active_scoped_not_name_inferred(self):
        series = self.series(teachers=[{"name": "mufti-b"}])
        self.assertEqual(series.teachers, [{"name": "mufti-b"}])
        self.directory.identities["mufti-b"] = replace(
            self.directory.identities["mufti-b"],
            case_keys=frozenset({self.receipts[1]["public_ref"]}),
        )
        with self.assertRaises(IdentityUnavailable):
            self.series(
                teachers=[
                    {
                        "name": "معلم",
                        "provider_id": self.directory.provider_id,
                        "subject_id": "mufti-b",
                    }
                ]
            )
        self.assertEqual(LessonSeries.objects.count(), 1)

    def test_teacher_revocation_during_write_rolls_back_initial_identity_and_version(self):
        original = services._save

        def revoke(row):
            result = original(row)
            self.directory.identities["mufti-b"] = replace(
                self.directory.identities["mufti-b"], active=False
            )
            return result

        with (
            patch.object(services, "_save", side_effect=revoke),
            self.assertRaises(IdentityUnavailable),
        ):
            self.series(
                teachers=[
                    {
                        "name": "معلم",
                        "provider_id": self.directory.provider_id,
                        "subject_id": "mufti-b",
                    }
                ]
            )
        self.assertEqual(LessonSeries.objects.count(), 0)

    def test_text_search_remains_available_without_organization_and_explicit_filters_intersect(
        self,
    ):
        self.assertEqual(self.search(query="اصطناعي")["total"], 3)
        lesson = self.lesson()
        self.review(self.link(lesson))
        self.review(self.relation("RELATED"))
        self.assertEqual(self.search(lesson_id=str(lesson.lesson_id))["total"], 1)
        self.assertEqual(
            self.search(
                series_id=str(lesson.lesson.series_id),
                category_id=str(lesson.category_id),
                query="alpha",
                relation_kind="RELATED",
                related_case_ref=self.receipts[1]["public_ref"],
            )["total"],
            1,
        )
        self.assertEqual(self.search(lesson_id=str(lesson.lesson_id), query="beta")["total"], 0)
        self.assertEqual(
            self.search(relation_kind="RELATED", related_case_ref=self.receipts[0]["public_ref"])[
                "rows"
            ][0]["case_ref"],
            self.receipts[1]["public_ref"],
        )

    def test_proposed_rejected_withdrawn_links_do_not_satisfy_manual_search(self):
        row = self.relation("RELATED")
        self.assertEqual(self.search(relation_kind="RELATED")["total"], 0)
        self.review(row, "REJECT")
        self.assertEqual(self.search(relation_kind="RELATED")["total"], 0)
        other = self.relation("RELATED")
        self.review(other)
        self.review(other, "WITHDRAW")
        self.assertEqual(self.search(relation_kind="RELATED")["total"], 0)

    def test_case_scope_reduction_hides_link_and_target_without_leaking_counts(self):
        row = self.relation()
        self.review(row)
        old = self.directory.identities["mufti-a"]
        self.directory.identities["mufti-a"] = replace(
            old, case_keys=frozenset({self.receipt["public_ref"], self.receipts[2]["public_ref"]})
        )
        result = services.desk(**self.common())
        self.assertEqual(result["relations"], [])
        self.assertNotIn(self.receipts[1]["public_ref"], str(result["targets"]))
        self.assertEqual(self.search(relation_kind=row.kind)["total"], 0)

    def test_mid_batch_scope_reduction_rejects_entire_search(self):
        row = self.relation()
        self.review(row)
        original = services._link_projection

        def revoke(*args, **kwargs):
            value = original(*args, **kwargs)
            identity = self.directory.identities["mufti-a"]
            self.directory.identities["mufti-a"] = replace(
                identity, case_keys=frozenset({self.receipt["public_ref"]})
            )
            return value

        with (
            patch.object(services, "_link_projection", side_effect=revoke),
            self.assertRaises((cases.CaseConflict, IdentityUnavailable)),
        ):
            self.search(relation_kind=row.kind)

    def test_mid_projection_policy_revocation_and_provider_change_fail_closed(self):
        version = self.lesson()
        original = services._lesson

        def revoke(*args, **kwargs):
            value = original(*args, **kwargs)
            self.authority.revoke("READ_LESSON", "LESSON")
            return value

        with (
            patch.object(services, "_lesson", side_effect=revoke),
            self.assertRaises(cases.CaseConflict),
        ):
            services.read_lesson(**self.common(), lesson_version_id=version.pk)
        self.authority.denied.clear()
        with (
            patch.object(
                self.authority,
                "permits",
                side_effect=lambda **kw: (
                    setattr(self.directory, "provider_id", "changed-directory") or True
                ),
            ),
            self.assertRaises(cases.CaseConflict),
        ):
            services.read_lesson(**self.common(), lesson_version_id=version.pk)

    def test_valid_until_refresh_does_not_invalidate_stable_authorized_projection(self):
        original = self.directory.resolve

        def refresh(subject):
            old = original(subject)
            self.directory.identities[subject] = replace(
                old, valid_until=timezone.now() + timedelta(minutes=29)
            )
            return self.directory.identities[subject]

        with patch.object(self.directory, "resolve", side_effect=refresh):
            self.assertEqual(self.search()["total"], 3)

    def test_media_right_is_separate_and_source_integrity_is_checked_at_open(self):
        version = self.lesson()
        self.authority.revoke("READ_MEDIA", "LESSON")
        self.assertEqual(
            services.read_lesson(**self.common(), lesson_version_id=version.pk)["title"],
            version.title,
        )
        with self.assertRaises(cases.CaseConflict):
            services.open_lesson_media(**self.common(), lesson_version_id=version.pk)
        self.authority.denied.clear()
        with (
            patch.object(answer_media, "raw_for_part", return_value=b"changed recording"),
            self.assertRaises(cases.CaseConflict),
        ):
            services.read_lesson(**self.common(), lesson_version_id=version.pk)

    def test_concurrent_duplicate_relations_have_one_proposal(self):
        barrier = Barrier(2)

        def work(_):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    self.relation("DUPLICATE_OF")
                    return "accepted"
                except cases.CaseConflict:
                    return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(work, range(2))), ["accepted", "rejected"])
        self.assertEqual(CaseRelation.objects.count(), 1)

    def test_concurrent_opposite_superseding_decisions_cannot_form_cycle(self):
        first, second = self.relation("SUPERSEDES", 0, 1), self.relation("SUPERSEDES", 1, 0)
        barrier = Barrier(2)

        def work(row):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    self.review(row)
                    return "accepted"
                except (cases.CaseConflict, DatabaseError):
                    return "rejected"
            finally:
                close_old_connections()

        with (
            patch.object(services, "_cycle", return_value=False),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            self.assertCountEqual(list(pool.map(work, (first, second))), ["accepted", "rejected"])
        self.assertEqual(LinkDecision.objects.filter(action="APPROVE").count(), 1)

    def test_postgres_rejects_updates_deletes_orphan_identity_and_forged_seal(self):
        version = self.lesson()
        relation = self.relation()
        lesson_link = self.link(version)
        self.review(relation)
        self.review(lesson_link)
        for model in (
            LessonCategory,
            LessonSeries,
            SeriesVersion,
            Lesson,
            LessonVersion,
            CaseRelation,
            CaseLessonLink,
            LinkDecision,
        ):
            table = model._meta.db_table
            for operation in (f"UPDATE {table} SET id=id", f"DELETE FROM {table}"):
                with (
                    self.subTest(table=table, operation=operation),
                    self.assertRaises(DatabaseError),
                    transaction.atomic(),
                    connection.cursor() as cursor,
                ):
                    cursor.execute(operation)
        with self.assertRaises(DatabaseError), transaction.atomic():
            LessonSeries.objects.create(case_id=self.receipt["case_id"])
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        category = LessonCategory(
            case_id=self.receipt["case_id"],
            label="forged",
            command_id=uuid.uuid4(),
            subject_id="mufti-a",
            provider_id=self.directory.provider_id,
            auth_epoch="epoch-1",
            case_revision=3,
            evidence_version=1,
            canonical_payload="{}",
            sha256="0" * 64,
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            category.save(force_insert=True)

    def test_postgres_rejects_incorrect_source_and_review_sequence_even_with_resealed_row(self):
        version = self.lesson()
        version.pk, version.command_id, version.number = uuid.uuid4(), uuid.uuid4(), 2
        version.previous_sha256 = version.sha256
        version.source_snapshot = {**version.source_snapshot, "sha256": "0" * 64}
        with self.assertRaises(DatabaseError), transaction.atomic():
            services._save(version)
        relation = self.relation()
        decision = self.review(relation)
        decision.pk, decision.command_id, decision.sequence = uuid.uuid4(), uuid.uuid4(), 2
        decision.previous_sha256 = decision.sha256
        with self.assertRaises(DatabaseError), transaction.atomic():
            services._save(decision)

    def test_postgres_cycle_guard_works_without_python_cycle_preflight(self):
        self.review(self.relation("DUPLICATE_OF", 0, 1))
        reverse = self.relation("DUPLICATE_OF", 1, 0)
        with patch.object(services, "_cycle", return_value=False), self.assertRaises(DatabaseError):
            self.review(reverse)
        self.assertEqual(reverse.decisions.count(), 0)

    def test_sql_teacher_shape_rejects_missing_name_even_with_valid_content_seal(self):
        row = self.series()
        row.pk, row.command_id, row.number = uuid.uuid4(), uuid.uuid4(), 2
        row.previous_sha256 = row.sha256
        row.teachers = [{}]
        with self.assertRaises(DatabaseError), transaction.atomic():
            services._save(row)

    def test_internal_public_candidates_are_exact_approved_versions_without_private_text(self):
        lesson = self.lesson()
        relation, link = self.relation(), self.link(lesson)
        case = Case.objects.get(pk=self.receipt["case_id"])
        with self.assertRaises(cases.CaseConflict):
            services.approved_candidates_for_locked_case(
                case=case, answer_id=case.approved_answer_id
            )
        with transaction.atomic():
            self.assertEqual(
                services.approved_candidates_for_locked_case(
                    case=case, answer_id=case.approved_answer_id
                ),
                {"relations": [], "lessons": []},
            )
        self.review(relation)
        self.review(link)
        with transaction.atomic():
            result = services.approved_candidates_for_locked_case(
                case=case, answer_id=case.approved_answer_id
            )
        self.assertEqual(result["lessons"][0]["lesson_public_id"], str(lesson.lesson.public_id))
        self.assertEqual(
            result["lessons"][0]["teacher_keys"],
            [{"provider_id": self.directory.provider_id, "subject_id": "mufti-a"}],
        )
        self.assertEqual(result["relations"][0]["kind"], "REFERRED_BY_SHEIKH")
        self.assertNotIn(lesson.title, str(result))
        self.assertNotIn(lesson.provenance, str(result))
        self.assertNotIn(relation.reason, str(result))

    def test_fingerprint_catches_new_rows_empty_to_nonempty_and_latest_version_changes(self):
        ids = [row["case_id"] for row in self.receipts]
        with transaction.atomic():
            empty = services.projection_fingerprint(ids)
        row = self.relation()
        with transaction.atomic():
            pending = services.projection_fingerprint(ids)
        self.assertNotEqual(empty, pending)
        self.review(row)
        with transaction.atomic():
            approved = services.projection_fingerprint(ids)
        self.assertNotEqual(pending, approved)
        self.review(row, "WITHDRAW")
        with transaction.atomic():
            self.assertNotEqual(approved, services.projection_fingerprint(ids))

    def test_withdrawal_during_link_permission_rejects_already_read_rows_and_counts(self):
        relation = self.relation()
        self.review(relation)
        permits = self.authority.permits
        withdrawn = False

        def withdraw_during_read(**arguments):
            nonlocal withdrawn
            if (
                not withdrawn
                and arguments["action"] == "READ_LINK"
                and arguments["resource_id"] == str(relation.pk)
            ):
                withdrawn = True
                self.review(relation, "WITHDRAW")
            return permits(**arguments)

        with (
            patch.object(self.authority, "permits", side_effect=withdraw_during_read),
            self.assertRaises(cases.CaseConflict),
        ):
            self.search(relation_kind=relation.kind)
        self.assertTrue(withdrawn)
        self.assertEqual(relation.decisions.count(), 1)
        self.assertEqual(relation.decisions.get().action, "APPROVE")

    def test_a_lesson_cannot_take_a_file_from_another_case(self):
        other = self.receipts[1]
        saved = answer_media.save_multipart_answer(
            **self.common(other),
            **self.pins(other),
            text="تسجيل من قضية أخرى",
            files=[audio_fixture()],
        )
        part = AnswerPart.objects.get(manifest__answer_id=saved["answers"][-1]["id"], ordinal=2)
        with self.assertRaises(cases.CaseConflict):
            self.lesson(source_part_id=part.pk)
        self.assertEqual(Lesson.objects.count(), 0)

    def test_historical_link_filter_survives_denied_new_lesson_version(self):
        old = self.lesson()
        self.review(self.link(old))
        category = self.category("تصنيف درس جديد")
        series = SeriesVersion.objects.filter(series=old.lesson.series).latest("number")
        newer = services.save_lesson(
            **self.common(),
            **self.pins(),
            series_id=series.series_id,
            expected_series_version=series.number,
            lesson_id=old.lesson_id,
            expected_lesson_version=1,
            title="نسخة أحدث غير متاحة",
            category_id=category.pk,
            source_part_id=self.part.pk,
            provenance="تغيير تنظيمي صريح",
            command_id=uuid.uuid4(),
        )
        self.authority.revoke("READ_LESSON", str(newer.pk))
        result = self.search(lesson_id=str(old.lesson_id), category_id=str(old.category_id))
        self.assertEqual(result["total"], 1)
        self.assertEqual(
            result["rows"][0]["lesson_matches"][0]["lesson"]["version_id"], str(old.pk)
        )
        self.assertNotIn(newer.title, str(result["lessons"]))

    def test_recovery_fixture_has_every_table_and_rebuilds_policy_without_credentials(self):
        from . import recovery_support

        pins = recovery_support.populate()
        self.assertEqual(len(pins["tables"]), 8)
        self.assertTrue(all(pins["tables"].values()))
        self.assertNotIn("credential", str(pins))
        self.assertEqual(recovery_support.verify_restored(pins)["nonempty_tables"], 8)


HTTP_FEATURES = {
    **WEB_SETTINGS,
    **FEATURES,
    "ROOT_URLCONF": "config.campaign_urls",
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}


@override_settings(**HTTP_FEATURES)
class HTTPTests(Fixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        page = self.client.get("/casework/staff/login/")
        response = post(
            self.client,
            "/casework/staff/login/",
            {"credential": self.directory.credentials["mufti-a"]},
            page,
        )
        self.assertEqual(response.status_code, 303)
        self.page = self.client.get("/casework/staff/")

    def send(self, action, **changes):
        fields = {"action": action, "case_ref": self.receipt["public_ref"], **changes}
        response = post(self.client, "/casework/staff/", fields, self.page)
        if response.status_code == 200 and response.get("Content-Type", "").startswith("text/html"):
            self.page = response
        return response

    def mutation(self, action, **changes):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return self.send(
            action,
            revision=case.revision,
            evidence_version=case.evidence_version,
            command_id=str(uuid.uuid4()),
            **changes,
        )

    def test_native_relation_does_not_hold_case_locks_while_waiting_for_graph(self):
        graph_owned, native_waiting = Event(), Event()

        def other_graph_reader():
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
                    graph_owned.set()
                    if not native_waiting.wait(timeout=10):
                        return "native graph request missing"
                    # A public projection already owning the graph must be able
                    # to acquire its case rows without a cycle against native UI.
                    try:
                        list(Case.objects.order_by("pk").select_for_update(nowait=True))
                    except DatabaseError:
                        return "case locked before graph"
                    return "case available"
            finally:
                close_old_connections()

        def detect_graph_wait(execute, sql, params, many, context):
            if "pg_advisory_xact_lock(546131,1)" in sql:
                native_waiting.set()
            return execute(sql, params, many, context)

        with ThreadPoolExecutor(max_workers=1) as pool:
            peer = pool.submit(other_graph_reader)
            self.assertTrue(graph_owned.wait(timeout=10))
            target = Case.objects.get(pk=self.receipts[1]["case_id"])
            with connection.execute_wrapper(detect_graph_wait):
                response = self.mutation(
                    "relation_propose",
                    target=(
                        f"{target.pk}:{target.approved_answer_id}:"
                        f"{target.revision}:{target.evidence_version}"
                    ),
                    kind="REFERRED_BY_SHEIKH",
                    reason="إحالة بشرية لا تتسبب في دورة أقفال",
                )
            self.assertEqual(peer.result(timeout=10), "case available")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CaseRelation.objects.count(), 1)

    def test_authority_replaced_inside_final_read_callback_discards_native_html(self):
        relation = self.relation()
        self.review(relation)
        replacement = Authority(self.authority.refs)
        replacement.denied.add(("READ_LINK", relation.kind))
        render, permits = views.render, self.authority.permits
        rendered, replaced = False, False

        def finished_render(*args, **kwargs):
            nonlocal rendered
            response = render(*args, **kwargs)
            rendered = True
            return response

        def replace_authority(**arguments):
            nonlocal replaced
            if rendered and arguments["action"] == "READ_LINK":
                settings.FATWA_SCHOLARLY_LINKS_AUTHORITY = replacement
                replaced = True
            return permits(**arguments)

        with (
            override_settings(FATWA_SCHOLARLY_LINKS_AUTHORITY=self.authority),
            patch.object(views, "render", side_effect=finished_render),
            patch.object(self.authority, "permits", side_effect=replace_authority),
        ):
            response = self.send("scholarly_open")
        self.assertTrue(replaced)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertNotContains(response, relation.reason, status_code=409)

    def test_connected_native_category_series_lesson_link_review_and_search(self):
        response = self.send("open")
        self.assertContains(response, 'value="scholarly_open"')
        response = self.send("scholarly_open")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.mutation("lesson_category_create", label="قراءة متن").status_code, 200
        )
        self.assertEqual(
            self.mutation(
                "lesson_series_save",
                series_id="",
                series_version=0,
                title="سلسلة جديدة",
                teachers="معلم بشري",
                teacher_is_me="yes",
            ).status_code,
            200,
        )
        series, category = SeriesVersion.objects.get(), LessonCategory.objects.get()
        response = self.mutation(
            "lesson_save",
            series_id=str(series.series_id),
            series_version=series.number,
            lesson_id="",
            lesson_version=0,
            title="الدرس الموثق",
            category_id=str(category.pk),
            source_part_id=str(self.part.pk),
            provenance="اختيار بشري للمصدر الاصطناعي",
        )
        self.assertEqual(response.status_code, 200, response.content)
        lesson = LessonVersion.objects.get()
        case = Case.objects.get(pk=self.receipt["case_id"])
        response = self.mutation(
            "lesson_link_propose",
            lesson_target=f"{lesson.pk}:{case.revision}:{case.evidence_version}",
            start_ms="10",
            end_ms="50",
            reason="موضع المسألة",
        )
        self.assertEqual(response.status_code, 200, response.content)
        link = CaseLessonLink.objects.get()
        response = self.mutation(
            "scholarly_review",
            link_id=str(link.pk),
            link_kind="LESSON",
            transition="APPROVE",
            sequence=0,
            target_revision=case.revision,
            target_evidence_version=case.evidence_version,
            note="راجعت الربط المحدد",
        )
        self.assertEqual(response.status_code, 200, response.content)
        response = self.send(
            "scholarly_search",
            query="",
            series_id=str(series.series_id),
            lesson_id=str(lesson.lesson_id),
            category_id="",
            relation_kind="",
            related_case_ref="",
        )
        self.assertContains(response, "النتائج المطابقة والمتاحة: 1")
        self.assertNotContains(response, "PRIVATE-QUESTION")
        self.assertIn("no-store", response["Cache-Control"])

    def test_native_typed_relation_and_reverse_navigation_and_exact_filters(self):
        target = Case.objects.get(pk=self.receipts[1]["case_id"])
        response = self.mutation(
            "relation_propose",
            target=f"{target.pk}:{target.approved_answer_id}:{target.revision}:{target.evidence_version}",
            kind="REFERRED_BY_SHEIKH",
            reason="إحالة صريحة",
        )
        self.assertEqual(response.status_code, 200, response.content)
        row = CaseRelation.objects.get()
        response = self.mutation(
            "scholarly_review",
            link_id=str(row.pk),
            link_kind="RELATION",
            transition="APPROVE",
            sequence=0,
            target_revision=target.revision,
            target_evidence_version=target.evidence_version,
            note="تحقق بشري",
        )
        self.assertEqual(response.status_code, 200, response.content)
        response = self.send(
            "scholarly_search",
            query="",
            series_id="",
            lesson_id="",
            category_id="",
            relation_kind=row.kind,
            related_case_ref=target.public_ref,
        )
        self.assertContains(response, "النتائج المطابقة والمتاحة: 1")
        response = self.send("scholarly_open", case_ref=target.public_ref)
        self.assertContains(response, "إحالة واردة إلى هذه القضية")

    def test_reset_restores_empty_filters_and_full_authorized_text_scope(self):
        response = self.send(
            "scholarly_search",
            query="no-matching-text",
            series_id="",
            lesson_id="",
            category_id="",
            relation_kind="",
            related_case_ref="",
        )
        self.assertContains(response, "النتائج المطابقة والمتاحة: 0")
        response = self.send("scholarly_search_open")
        self.assertContains(response, "النتائج المطابقة والمتاحة: 3")
        self.assertContains(response, 'name="query" value=""')

    def test_unknown_duplicate_fields_and_missing_csrf_are_rejected(self):
        self.assertEqual(self.send("scholarly_open", actor="mufti-b").status_code, 400)
        self.assertEqual(
            self.client.post(
                "/casework/staff/",
                {"action": "scholarly_open", "case_ref": self.receipt["public_ref"]},
            ).status_code,
            403,
        )
        data = urlencode(
            [
                ("csrfmiddlewaretoken", hidden(self.page, "csrfmiddlewaretoken")),
                ("action", "scholarly_open"),
                ("action", "scholarly_open"),
                ("case_ref", self.receipt["public_ref"]),
            ]
        )
        self.assertEqual(
            self.client.post(
                "/casework/staff/", data, content_type="application/x-www-form-urlencoded"
            ).status_code,
            400,
        )

    def test_revocation_during_template_composition_does_not_release_private_titles(self):
        self.lesson(title="PRIVATE-LESSON-TITLE")
        original = views.render

        def revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            self.authority.revoke("READ_LESSON", "LESSON")
            return response

        with patch.object(views, "render", side_effect=revoke):
            response = self.send("scholarly_open")
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, "PRIVATE-LESSON-TITLE", status_code=409)

    def test_late_native_withdrawal_invalidates_rendered_links_and_rolls_back_composition(self):
        relation = self.relation()
        self.review(relation)
        original = views.render

        def withdraw(*args, **kwargs):
            response = original(*args, **kwargs)
            self.review(relation, "WITHDRAW")
            return response

        with patch.object(views, "render", side_effect=withdraw):
            response = self.send("scholarly_open")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertNotContains(response, "ربط اعتمده إنسان", status_code=409)
        self.assertEqual(services._status(relation)[0], "APPROVE")

    def test_late_native_followup_invalidates_result_count_and_canonical_snapshot(self):
        original = views.render
        before = self.pins()

        def followup(*args, **kwargs):
            response = original(*args, **kwargs)
            cases.add_followup(
                token=self.receipt["token"],
                text="وقائع وصلت أثناء التركيب",
                expected_revision=before["expected_revision"],
                synthetic_fixtures_only=True,
            )
            return response

        with patch.object(views, "render", side_effect=followup):
            response = self.send("scholarly_search_open")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertNotContains(response, "النتائج المطابقة", status_code=409)
        self.assertEqual(self.pins(), before)

    def test_late_series_version_change_invalidates_native_lesson_cards(self):
        lesson = self.lesson()
        version = SeriesVersion.objects.filter(series=lesson.lesson.series).latest("number")
        original = views.render

        def rename(*args, **kwargs):
            response = original(*args, **kwargs)
            self.series(
                series_id=version.series_id,
                expected_series_version=version.number,
                title="عنوان تغير أثناء تركيب الصفحة",
            )
            return response

        with patch.object(views, "render", side_effect=rename):
            response = self.send("scholarly_open")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(
            SeriesVersion.objects.filter(series=version.series).latest("number").pk, version.pk
        )

    def test_source_bytes_and_descriptive_lesson_without_false_media_control(self):
        lesson = self.lesson()
        response = self.send("lesson_media", lesson_version_id=str(lesson.pk))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(sha256(response.content).hexdigest(), self.part.sha256)
        self.assertIn("no-store", response["Cache-Control"])
        descriptive = self.lesson(category=lesson.category, source_part_id=None)
        response = self.send("lesson_view", lesson_version_id=str(descriptive.pk))
        self.assertNotContains(response, 'value="lesson_media"')
        self.assertContains(response, "دون ملف رقمي مختار")

    def test_staff_scope_required_for_both_endpoints_and_requester_cannot_create_links(self):
        row = self.relation()
        self.directory.identities["mufti-a"] = replace(
            self.directory.identities["mufti-a"], case_keys=frozenset({self.receipt["public_ref"]})
        )
        target = Case.objects.get(pk=self.receipts[1]["case_id"])
        response = self.mutation(
            "scholarly_review",
            link_id=str(row.pk),
            link_kind="RELATION",
            transition="APPROVE",
            sequence=0,
            target_revision=target.revision,
            target_evidence_version=target.evidence_version,
            note="غير مسموح",
        )
        self.assertEqual(response.status_code, 409)
        outsider = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = outsider.get("/casework/staff/login/")
        response = post(
            outsider,
            "/casework/staff/",
            {"action": "scholarly_open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(LinkDecision.objects.count(), 0)
