"""Generated sources and explicit scoped authorities for teaching proofs."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.casework.models import Case
from apps.public_answer_media.test_support import audio
from apps.public_knowledge.models import PublicRevision
from apps.public_knowledge.test_scholarly import INTEGRATED, IntegratedFixture
from apps.research_library import services as library
from apps.research_library.models import LibraryVersion
from apps.research_library.test_support import (
    FEATURES as LIBRARY_FEATURES,
)
from apps.research_library.test_support import (
    FixtureAuthority as LibraryAuthority,
)
from apps.research_library.test_support import (
    bind_identity_snapshot,
    payload,
)
from apps.scholarly_links import services as links
from apps.scholarly_links.models import SeriesVersion

from . import services
from .authority import TeachingAuthority
from .models import TeachingVersion

FEATURES = {
    **INTEGRATED,
    **LIBRARY_FEATURES,
    "FATWA_PUBLIC_TEACHING_ENABLED": True,
    "FATWA_PUBLIC_TEACHING_PUBLIC_ENABLED": True,
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
}
MATERIAL = "مادة عامة اصطناعية محفوظة الأصل، لا تحتوي فتوى حقيقية.\n".encode()
CREDENTIALS = {
    "editor": "synthetic-editor-credential-32-characters",
    "other": "synthetic-reviewer-credential-32-characters",
    "publisher": "synthetic-publisher-credential-32-characters",
}


class FixtureAuthority(TeachingAuthority):
    def __init__(self, refs, *, provider_id="synthetic-publication-directory"):
        self.refs = set(refs)
        self.provider_id = provider_id
        self.denied = set()
        self.until = timezone.now() + timedelta(minutes=30)
        self.hook = None

    def projection_epoch(self):
        return repr(
            (
                self.provider_id,
                sorted(self.refs),
                sorted(self.denied, key=repr),
                self.until.isoformat(),
            )
        )

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == self.provider_id
            and values["subject_id"] in CREDENTIALS
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] in self.refs
            and values["action"]
            in {
                "READ",
                "WRITE",
                "REVIEW",
                "APPROVE",
                "RELEASE",
                "WITHDRAW",
                "READ_SOURCE",
                "PUBLIC_LESSON_CONTENT",
            }
            and values["kind"]
            in {
                "WORKSPACE",
                "SCHOLAR_MATERIAL",
                "SCHOLAR",
                "LIBRARY",
                "LESSON",
                "LESSON_METADATA",
                "SERIES",
                "TEACHING_LESSON",
                "ANSWER_MEDIA",
            }
            and values["action"] not in self.denied
            and (values["action"], values["kind"]) not in self.denied
            and (values["action"], values["resource_id"]) not in self.denied
            and (values["subject_id"], values["action"]) not in self.denied
            and timezone.now() < self.until
        )

    def grant_deadline(self, **values):
        return self.until if self.permits(**values) else None


class TeachingFixture(IntegratedFixture):
    def setUp(self):
        with patch(
            "apps.public_knowledge.test_scholarly.audio_fixture",
            return_value={
                "raw": audio(),
                "filename": "private-source.wav",
                "media_type": "audio/wav",
            },
        ):
            super().setUp()
        bind_identity_snapshot(self.directory)
        refs = [self.receipt["public_ref"], self.second["public_ref"]]
        self.teaching_authority = FixtureAuthority(refs, provider_id=self.directory.provider_id)
        self.library_authority = LibraryAuthority(*refs, provider_id=self.directory.provider_id)
        configured = override_settings(
            FATWA_PUBLIC_TEACHING_AUTHORITY=self.teaching_authority,
            FATWA_RESEARCH_LIBRARY_AUTHORITY=self.library_authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def material(self):
        row = library.write_material(
            **self.common,
            **self.pins(),
            namespace="synthetic-teaching",
            external_id=uuid.uuid4().hex,
            payload=payload(
                "DOCUMENT", title="المادة العامة المنسوبة", creator="اسم ليس هوية مستخدم"
            ),
            file_bytes=MATERIAL,
            filename="material.txt",
            media_type="text/plain",
            expected_version=0,
            request_key=uuid.uuid4(),
        )
        for command, subject in (
            ("REVIEW", "other"),
            ("APPROVE", "publisher"),
            ("RELEASE", "publisher"),
        ):
            row = library.decide(
                **{**self.common, "subject_id": subject},
                **self.pins(),
                version_id=row["version_id"],
                action=command,
                note="مراجعة أصل اصطناعي ونسبته وإتاحته",
                expected_actions=row["action_count"],
                request_key=uuid.uuid4(),
                confirmed=True,
                uses=["READ", "DOWNLOAD", "PUBLIC_METADATA", "PUBLIC_CONTENT"]
                if command == "APPROVE"
                else [],
                minutes=30 if command == "APPROVE" else 15 if command == "RELEASE" else 0,
            )
        return LibraryVersion.objects.get(pk=row["version_id"])

    def metadata(self):
        scholar = self.release_record(self.save_record("SCHOLAR"))
        first, _ = self.lesson()
        self.first = first
        metadata = self.release_record(self.lesson_record(first, scholar_ids=[scholar["id"]]))
        latest = (
            SeriesVersion.objects.filter(series_id=first.lesson.series_id)
            .order_by("-number")
            .first()
        )
        second = links.save_lesson(
            **self.second_common(),
            **self.pins(self.second),
            series_id=latest.series_id,
            expected_series_version=latest.number,
            title="عنوان درس داخلي ثان",
            category_id=first.category_id,
            source_part_id=self.part.pk,
            provenance="أصل اصطناعي للدرس الثاني",
            command_id=uuid.uuid4(),
        )
        target = Case.objects.get(pk=self.second["case_id"])
        link = links.propose_lesson_link(
            **self.common,
            **self.pins(),
            lesson_version_id=second.pk,
            expected_target_revision=target.revision,
            expected_target_evidence_version=target.evidence_version,
            reason="ربط بشري اصطناعي بدرس ثان",
            start_ms=1000,
            end_ms=2500,
            command_id=uuid.uuid4(),
        )
        self.review_link(link)
        second_metadata = self.release_record(
            self.lesson_record(second, scholar_ids=[scholar["id"]])
        )
        return (
            PublicRevision.objects.get(pk=scholar["id"]),
            PublicRevision.objects.get(pk=metadata["id"]),
            PublicRevision.objects.get(pk=second_metadata["id"]),
        )

    def save_teaching(self, kind, **changes):
        return services.save(
            **{
                **self.common,
                **self.pins(),
                "kind": kind,
                "title": "إتاحة تعليمية اصطناعية",
                "summary": "وصف عام محرر دون بيانات خاصة",
                "note": "اختيار بشري للنسخة والنسبة",
                "request_key": uuid.uuid4(),
                "confirmed": True,
                **changes,
            }
        )

    def teaching_decision(self, row, command, **changes):
        return services.decide(
            **{
                **self.common,
                **self.pins(),
                "subject_id": "other" if command == "REVIEW" else "publisher",
                "version_id": row["id"],
                "command": command,
                "expected_actions": row["action_count"],
                "request_key": uuid.uuid4(),
                "note": "مراجعة مستقلة للنسخة والإتاحة الحالية",
                "confirmed": True,
                "minutes": 15 if command == "RELEASE" else 0,
                **changes,
            }
        )

    def release_teaching(self, row):
        for command in ("REVIEW", "APPROVE", "RELEASE"):
            row = self.teaching_decision(row, command)
        return row

    def complete(self):
        scholar, first, second = self.metadata()
        material = self.material()
        attribution = self.release_teaching(
            self.save_teaching(
                "SCHOLAR_MATERIAL",
                title="مادة عامة منسوبة بمراجعة",
                profile=services.selection(scholar),
                material=services.selection(material),
                attribution="نسبة بشرية اصطناعية محددة؛ ليست مطابقة اسم تلقائية",
            )
        )
        lessons = [
            self.release_teaching(
                self.save_teaching(
                    "LESSON", title=f"درس عام {index}", lesson=services.selection(record)
                )
            )
            for index, record in enumerate((first, second), 1)
        ]
        series = (
            SeriesVersion.objects.filter(series_id=self.first.lesson.series_id)
            .order_by("-number")
            .first()
        )
        release = self.release_teaching(
            self.save_teaching(
                "SERIES",
                title="سلسلة عامة ذات ترتيب موثق",
                topic="موضوع تجريبي",
                series=services.selection(series),
                members=[
                    services.selection(TeachingVersion.objects.get(pk=row["id"])) for row in lessons
                ],
            )
        )
        return {
            "scholar": scholar,
            "material": material,
            "attribution": attribution,
            "lessons": lessons,
            "series": release,
        }
