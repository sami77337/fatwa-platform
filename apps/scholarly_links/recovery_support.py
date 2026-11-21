"""Synthetic-only population and fresh-process verification for encrypted recovery.

Policies are rebuilt locally from explicit fixture case references. Credentials
and policy objects are never serialized into pins or recovery artifacts.
"""

import uuid
from contextlib import contextmanager
from hashlib import sha256

from django.test import override_settings

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.case_assignments.tests import Directory
from apps.casework import services as cases
from apps.casework.models import Case

from . import services
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
from .tests import Authority

MODELS = (
    LessonCategory,
    LessonSeries,
    SeriesVersion,
    Lesson,
    LessonVersion,
    CaseRelation,
    CaseLessonLink,
    LinkDecision,
)
TABLES = tuple(model._meta.db_table for model in MODELS)
FUNCTIONS = ("sl_identity_guard()", "sl_identity_complete()", "sl_sealed_guard()")
TRIGGERS = (
    "sl_series_identity",
    "sl_lesson_identity",
    "sl_series_complete",
    "sl_lesson_complete",
    "sl_lessoncategory_guard",
    "sl_seriesversion_guard",
    "sl_lessonversion_guard",
    "sl_caserelation_guard",
    "sl_caselessonlink_guard",
    "sl_linkdecision_guard",
)


@contextmanager
def _fixture(refs):
    directory = Directory(refs)
    authority = Authority(refs)
    with override_settings(
        FATWA_SCHOLARLY_LINKS_ENABLED=True,
        FATWA_ANSWER_MEDIA_ENABLED=True,
        FATWA_SCHOLARLY_LINKS_AUTHORITY=authority,
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
    ):
        yield directory


def _common(receipt, directory):
    return dict(
        case_id=receipt["case_id"],
        subject_id="mufti-a",
        provider=directory,
        synthetic_fixtures_only=True,
    )


def _pins(receipt):
    case = Case.objects.get(pk=receipt["case_id"])
    return dict(expected_revision=case.revision, expected_evidence_version=case.evidence_version)


def populate():
    seed_key = uuid.uuid4().hex
    receipts = [
        cases.intake_case(
            original_question=f"سؤال استعادة اصطناعي {suffix}",
            requester_id="scholarly-recovery-" + seed_key + "-" + suffix,
            source_event_id="scholarly-recovery-" + seed_key + "-" + suffix,
            idempotency_key="scholarly-recovery-" + seed_key + "-" + suffix,
            synthetic_fixtures_only=True,
        )
        for suffix in ("a", "b")
    ]
    with _fixture([row["public_ref"] for row in receipts]) as directory:
        for receipt in receipts:
            saved = media.save_multipart_answer(
                **_common(receipt, directory),
                **_pins(receipt),
                text="جواب بشري اصطناعي للاستعادة",
                files=[audio_fixture()],
            )
            cases.record_decision(
                **_common(receipt, directory),
                **_pins(receipt),
                answer_id=saved["answers"][-1]["id"],
                action="APPROVE",
                note="اعتماد اصطناعي",
            )
        common = _common(receipts[0], directory)
        category = services.create_category(
            **common, **_pins(receipts[0]), label="قراءة متن اصطناعي", command_id=uuid.uuid4()
        )
        series = services.save_series(
            **common,
            **_pins(receipts[0]),
            title="سلسلة استعادة اصطناعية",
            teachers=[
                {
                    "name": "معلم اصطناعي",
                    "provider_id": directory.provider_id,
                    "subject_id": "mufti-a",
                }
            ],
            command_id=uuid.uuid4(),
        )
        part = AnswerPart.objects.get(manifest__answer__case_id=receipts[0]["case_id"], ordinal=2)
        lesson = services.save_lesson(
            **common,
            **_pins(receipts[0]),
            series_id=series.series_id,
            expected_series_version=1,
            title="درس الاستعادة",
            category_id=category.pk,
            provenance="مرجع إدخال اصطناعي صريح",
            source_part_id=part.pk,
            command_id=uuid.uuid4(),
        )
        first_case, target_case = [Case.objects.get(pk=row["case_id"]) for row in receipts]
        relation = services.propose_relation(
            **common,
            **_pins(receipts[0]),
            target_case_id=target_case.pk,
            target_answer_id=target_case.approved_answer_id,
            expected_target_revision=target_case.revision,
            expected_target_evidence_version=target_case.evidence_version,
            kind="REFERRED_BY_SHEIKH",
            reason="إحالة اصطناعية محددة",
            command_id=uuid.uuid4(),
        )
        link = services.propose_lesson_link(
            **common,
            **_pins(receipts[0]),
            lesson_version_id=lesson.pk,
            start_ms=10,
            end_ms=50,
            reason="موضع محفوظ في التسجيل الأصلي",
            expected_target_revision=first_case.revision,
            expected_target_evidence_version=first_case.evidence_version,
            command_id=uuid.uuid4(),
        )
        for row, kind, target in (
            (relation, "RELATION", target_case),
            (link, "LESSON", first_case),
        ):
            services.review_link(
                **common,
                **_pins(receipts[0]),
                link_id=row.pk,
                link_kind=kind,
                action="APPROVE",
                note="قرار مراجعة بشري اصطناعي",
                expected_sequence=0,
                expected_target_revision=target.revision,
                expected_target_evidence_version=target.evidence_version,
                command_id=uuid.uuid4(),
            )
        tables = {}
        for model in MODELS:
            names = ("id", "sha256") if hasattr(model, "sha256") else ("id", "public_id")
            tables[model._meta.db_table] = [
                [str(value) for value in row]
                for row in model.objects.order_by("id").values_list(*names)
            ]
            if not tables[model._meta.db_table]:
                raise AssertionError("scholarly recovery fixture table is empty")
        return {
            "cases": [
                {"case_id": row["case_id"], "public_ref": row["public_ref"]} for row in receipts
            ],
            "lesson_version_id": str(lesson.pk),
            "lesson_sha256": lesson.sha256,
            "lesson_public_id": str(lesson.lesson.public_id),
            "part_sha256": part.sha256,
            "relation_id": str(relation.pk),
            "link_id": str(link.pk),
            "tables": tables,
        }


def verify_restored(pins):
    receipts = pins["cases"]
    with _fixture([row["public_ref"] for row in receipts]) as directory:
        common = _common(receipts[0], directory)
        result = services.desk(**common)
        relation = next(row for row in result["relations"] if row["id"] == pins["relation_id"])
        link = next(row for row in result["lesson_links"] if row["id"] == pins["link_id"])
        if relation["state"] != "APPROVE" or link["state"] != "APPROVE":
            raise AssertionError("restored scholarly approval changed")
        if (
            link["lesson"]["version_id"],
            link["lesson"]["sha256"],
            link["lesson"]["public_id"],
            link["start_ms"],
            link["end_ms"],
        ) != (pins["lesson_version_id"], pins["lesson_sha256"], pins["lesson_public_id"], 10, 50):
            raise AssertionError("restored exact lesson/source pins changed")
        media_result = services.open_lesson_media(
            **common, lesson_version_id=pins["lesson_version_id"]
        )
        if sha256(media_result["raw"]).hexdigest() != pins["part_sha256"]:
            raise AssertionError("restored lesson original differs")
        for model in MODELS:
            expected = pins["tables"][model._meta.db_table]
            names = ("id", "sha256") if hasattr(model, "sha256") else ("id", "public_id")
            found = [
                [str(value) for value in row]
                for row in model.objects.filter(id__in=[row[0] for row in expected])
                .order_by("id")
                .values_list(*names)
            ]
            if found != expected:
                raise AssertionError("restored scholarly immutable inventory differs")
        return {
            "tables": len(MODELS),
            "nonempty_tables": len(TABLES),
            "exact_lesson_media": True,
            "approved_links": 2,
            "fresh_policy": True,
        }
