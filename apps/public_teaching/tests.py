"""Whole original scholar material and ordered lesson/series behavior."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256

from django.core.management import call_command
from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvent
from apps.library_preview import services as preview
from apps.public_answer_media.test_support import audio
from apps.public_knowledge.models import PublicRevision
from apps.research_library import services as library
from apps.scholarly_links import services as links
from apps.scholarly_links.models import SeriesVersion

from . import services
from .models import TeachingAction, TeachingItem, TeachingVersion
from .test_support import FEATURES, MATERIAL, TeachingFixture


@override_settings(**FEATURES)
class TeachingTests(TeachingFixture, TransactionTestCase):
    def attribution_draft(self, **changes):
        scholar = self.release_record(self.save_record("SCHOLAR"))
        material = self.material()
        return self.save_teaching(
            "SCHOLAR_MATERIAL",
            profile=services.selection(PublicRevision.objects.get(pk=scholar["id"])),
            material=services.selection(material),
            attribution="نسبة بشرية مستقلة للمصدر المحدد",
            **changes,
        )

    def test_scholar_shows_actual_fatwas_lessons_and_exact_attributed_material(self):
        rows = self.complete()
        with services.public_projection() as current:
            result = current.scholar(str(rows["scholar"].series_id))
            self.assertTrue(result["publications"])
            self.assertEqual(len(result["lessons"]), 2)
            self.assertEqual(len(result["materials"]), 1)
            material = result["materials"][0]
            self.assertEqual(material["material"]["file"]["sha256"], sha256(MATERIAL).hexdigest())
            self.assertIn("بشرية", material["attribution"])
            self.assertNotIn("PRIVATE", str(result))
            self.assertNotIn(self.receipt["public_ref"], str(result))
            self.assertNotIn("auth_epoch", str(result))
        self.assertEqual(TeachingItem.objects.count(), 4)
        self.assertEqual(TeachingVersion.objects.count(), 4)
        self.assertEqual(TeachingAction.objects.count(), 12)

    def test_series_opens_reviewed_original_and_previous_next_keep_stable_ids(self):
        rows = self.complete()
        before = (
            list(AnswerRevision.objects.values()),
            list(CaseEvent.objects.values()),
            services.history(),
        )
        first, second = rows["lessons"]
        with services.public_projection() as current:
            series = current.read(rows["series"]["public_id"], "SERIES")[1]
            self.assertEqual(
                [row["id"] for row in series["members"]], [first["public_id"], second["public_id"]]
            )
            lesson = current.lesson(first["public_id"], series_id=rows["series"]["public_id"])
            self.assertIsNone(lesson["previous"])
            self.assertIn(second["public_id"], lesson["next"]["url"])
            later = current.lesson(second["public_id"], series_id=rows["series"]["public_id"])
            self.assertIsNone(later["next"])
            self.assertIn(first["public_id"], later["previous"]["url"])
            self.assertEqual(current.audio(first["public_id"], 1)["raw"], audio())
        self.assertEqual(
            before,
            (
                list(AnswerRevision.objects.values()),
                list(CaseEvent.objects.values()),
                services.history(),
            ),
        )

    def test_explicit_independent_review_and_release_are_not_inferred_from_source(self):
        row = self.attribution_draft()
        with services.public_projection() as current:
            self.assertEqual(list(current.catalog()["scholars"]), [])
        with self.assertRaisesMessage(cases.CaseConflict, "teaching_independent_actor_required"):
            self.teaching_decision(row, "REVIEW", subject_id="editor")
        reviewed = self.teaching_decision(row, "REVIEW")
        with self.assertRaisesMessage(cases.CaseConflict, "teaching_independent_actor_required"):
            self.teaching_decision(reviewed, "APPROVE", subject_id="other")
        approved = self.teaching_decision(reviewed, "APPROVE")
        with services.public_projection() as current:
            self.assertEqual(list(current.catalog()["scholars"]), [])
        released = self.teaching_decision(approved, "RELEASE")
        with services.public_projection() as current:
            self.assertEqual(len(current.rows), 1)
        self.assertEqual(released["state"], "RELEASE")

    def test_exact_selection_cas_idempotency_and_concurrent_edit_never_replace_history(self):
        row = self.attribution_draft()
        old = TeachingVersion.objects.get(pk=row["id"])
        values = dict(
            profile=services.selection(old.profile),
            material=services.selection(old.library_version),
            attribution="نسبة مصححة محفوظة",
            item_id=row["item_id"],
            expected_version=1,
            request_key=uuid.uuid4(),
        )
        with self.assertRaisesMessage(cases.CaseConflict, "teaching_selection_changed"):
            self.save_teaching(
                "SCHOLAR_MATERIAL",
                **{**values, "material": str(old.library_version_id) + "|" + "0" * 64},
            )
        second = self.save_teaching("SCHOLAR_MATERIAL", **values)
        self.assertEqual(self.save_teaching("SCHOLAR_MATERIAL", **values)["id"], second["id"])
        with self.assertRaisesMessage(cases.CaseConflict, "teaching_request_conflict"):
            self.save_teaching("SCHOLAR_MATERIAL", **{**values, "title": "تغيير طلب محفوظ"})
        with self.assertRaisesMessage(cases.CaseConflict, "teaching_version_changed"):
            self.save_teaching("SCHOLAR_MATERIAL", **{**values, "request_key": uuid.uuid4()})

        def edit(index):
            connections.close_all()
            try:
                return self.save_teaching(
                    "SCHOLAR_MATERIAL",
                    **{
                        **values,
                        "title": f"تصحيح متزامن {index}",
                        "expected_version": 2,
                        "request_key": uuid.uuid4(),
                    },
                )["number"]
            except cases.CaseConflict as exc:
                return str(exc)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(edit, (1, 2)))
        self.assertEqual(outcomes.count(3), 1)
        self.assertEqual(
            outcomes.count("teaching_version_changed")
            + outcomes.count("teaching_projection_changed"),
            1,
        )
        self.assertEqual(TeachingVersion.objects.count(), 3)
        self.assertEqual(TeachingVersion.objects.get(pk=old.pk).digest, old.digest)

    def test_series_reorder_requires_new_reviewed_release_and_keeps_lesson_identity(self):
        rows = self.complete()
        old = TeachingVersion.objects.get(pk=rows["series"]["id"])
        latest = (
            SeriesVersion.objects.filter(series=old.series_version.series)
            .order_by("-number")
            .first()
        )
        moved = links.move_lesson(
            **self.second_common(),
            **self.pins(self.second),
            series_id=latest.series_id,
            lesson_id=self.first.lesson_id,
            direction="down",
            expected_series_version=latest.number,
            command_id=uuid.uuid4(),
        )
        members = list(reversed(rows["lessons"]))
        candidate = self.save_teaching(
            "SERIES",
            title="إصدار ترتيب جديد",
            item_id=rows["series"]["item_id"],
            expected_version=1,
            series=services.selection(moved),
            members=[row["selection"] for row in members],
        )
        with services.public_projection() as current:
            self.assertEqual(current.read(rows["series"]["public_id"], "SERIES")[1]["number"], 1)
        released = self.release_teaching(candidate)
        self.assertEqual(released["public_id"], rows["series"]["public_id"])
        with services.public_projection() as current:
            series = current.read(released["public_id"], "SERIES")[1]
            self.assertEqual(
                [row["id"] for row in series["members"]], [row["public_id"] for row in members]
            )
        self.teaching_decision(released, "WITHDRAW")
        with services.public_projection() as current:
            with self.assertRaises(preview.PreviewUnavailable):
                current.read(released["public_id"], "SERIES")
        self.assertEqual(TeachingVersion.objects.get(pk=old.pk).digest, old.digest)

    def test_public_media_requires_separate_current_content_and_source_permissions(self):
        rows = self.complete()
        first = rows["lessons"][0]
        for denied in ("PUBLIC_LESSON_CONTENT", ("READ_SOURCE", "LESSON")):
            self.teaching_authority.denied.add(denied)
            with services.public_projection() as current:
                with self.assertRaises(preview.PreviewUnavailable):
                    current.audio(first["public_id"], 1)
                self.assertFalse(current.catalog()["series"])
            self.teaching_authority.denied.remove(denied)
        self.link_authority.denied.add(("READ_MEDIA", "LESSON"))
        with services.public_projection() as current:
            with self.assertRaises(preview.PreviewUnavailable):
                current.audio(first["public_id"], 1)
        self.link_authority.denied.clear()
        with services.public_projection() as current:
            self.assertEqual(current.audio(first["public_id"], 1)["raw"], audio())

    def test_source_withdrawal_revoked_actor_and_literal_flags_deny_without_resurrecting(self):
        row = self.release_teaching(self.attribution_draft())
        for setting, value in (
            ("FATWA_PUBLIC_TEACHING_ENABLED", False),
            ("FATWA_PUBLIC_TEACHING_ENABLED", 1),
            ("FATWA_PUBLIC_TEACHING_PUBLIC_ENABLED", False),
            ("FATWA_PUBLIC_TEACHING_AUTHORITY", None),
            ("FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with (
                override_settings(**{setting: value}),
                self.assertRaises(preview.PreviewUnavailable),
            ):
                with services.public_projection():
                    pass
        old = self.directory.identities["publisher"]
        self.directory.identities["publisher"] = replace(old, active=False)
        with self.assertRaises(preview.PreviewUnavailable):
            with services.public_projection():
                pass
        self.directory.identities["publisher"] = old
        source = TeachingVersion.objects.get(pk=row["id"]).library_version
        result = library.read_material(**self.common, version_id=source.pk)
        library.decide(
            **{**self.common, "subject_id": "publisher"},
            **self.pins(),
            version_id=source.pk,
            action="WITHDRAW",
            note="سحب المصدر الاصطناعي",
            expected_actions=result["action_count"],
            request_key=uuid.uuid4(),
            confirmed=True,
        )
        with services.public_projection() as current:
            self.assertNotIn(row["public_id"], current.rows)

    def test_retained_projection_discards_late_policy_or_identity_revocation(self):
        row = self.release_teaching(self.attribution_draft())
        for mutate, restore in (
            (
                lambda: self.teaching_authority.denied.add("READ_SOURCE"),
                lambda: self.teaching_authority.denied.clear(),
            ),
            (
                lambda: self.directory.identities.update(
                    publisher=replace(self.directory.identities["publisher"], active=False)
                ),
                lambda: self.directory.identities.update(
                    publisher=replace(self.directory.identities["publisher"], active=True)
                ),
            ),
        ):
            with self.assertRaises(preview.PreviewUnavailable):
                with services.public_projection() as current:
                    self.assertIn(row["public_id"], current.rows)
                    mutate()
            restore()
        with services.public_projection() as current:
            self.assertIn(row["public_id"], current.rows)

    def test_sql_append_only_and_resealed_source_or_actor_forgery_are_rejected(self):
        released = self.release_teaching(self.attribution_draft())
        row = TeachingVersion.objects.get(pk=released["id"])
        for model in (TeachingItem, TeachingVersion, TeachingAction):
            instance = model.objects.first()
            for action in ("update", "delete"):
                with (
                    self.subTest(model=model.__name__, action=action),
                    self.assertRaises(IntegrityError),
                    transaction.atomic(),
                ):
                    with connection.cursor() as cursor:
                        statement = (
                            f'UPDATE "{model._meta.db_table}" SET created_at=created_at WHERE id=%s'
                            if action == "update"
                            else f'DELETE FROM "{model._meta.db_table}" WHERE id=%s'
                        )
                        cursor.execute(statement, [instance.pk])
        values = {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}
        for changes in (
            {
                "source_pins": {
                    **row.source_pins,
                    "library": {**row.source_pins["library"], "sha256": "0" * 64},
                }
            },
            {"profile_id": row.library_version_id},
        ):
            forged = TeachingVersion(
                **{
                    **values,
                    "id": uuid.uuid4(),
                    "request_key": uuid.uuid4(),
                    "number": 2,
                    "previous_digest": row.digest,
                    **changes,
                }
            )
            with self.assertRaises(IntegrityError), transaction.atomic():
                library._seal(forged)
        self.assertEqual(TeachingVersion.objects.count(), 1)

    def test_populated_migration_reversal_restores_exact_guards_and_history(self):
        self.release_teaching(self.attribution_draft())
        before = services.history()
        call_command("migrate", "public_teaching", "0001", verbosity=0)
        call_command("migrate", "public_teaching", verbosity=0)
        self.assertEqual(services.history(), before)
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE public_teaching_teachingaction SET note='forged'")
