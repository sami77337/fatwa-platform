"""Finite current case/version grants and service-created lessons, with no role aliases."""

import uuid
from dataclasses import replace

from django.test import override_settings
from django.utils import timezone

from apps.answer_media.models import AnswerPart
from apps.casework.models import Case
from apps.scholarly_links import services as scholarly
from apps.scholarly_links.authority import ScholarlyAuthority
from apps.scholarly_links.models import CaseLessonLink, LinkDecision, SeriesVersion

from . import lesson_links
from .boundary import digest, source_rows
from .notes_test_support import NOTE_FEATURES, NoteFixture
from .test_support import Authority, Directory, approved

LESSON_FEATURES = {
    **NOTE_FEATURES,
    "FATWA_OPERATIONAL_LESSON_LINKS_ENABLED": True,
    "FATWA_SCHOLARLY_LINKS_ENABLED": True,
}


class SeedAuthority(ScholarlyAuthority):
    def __init__(self, common, ref):
        self.common, self.ref = common, ref

    def projection_epoch(self):
        return "explicit-synthetic-lesson-seed-v1"

    def permits(self, **values):
        return (
            values["provider_id"] == self.common["provider"].provider_id
            and values["subject_id"] == self.common["subject_id"]
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] == values["target_case_ref"] == self.ref
            and values["action"] in {"MANAGE_LESSONS", "READ_LESSON", "READ_MEDIA"}
            and values["kind"] in {"LESSON", "SERIES", "CATEGORY"}
        )


class LessonAuthority(Authority):
    def __init__(self, receipts):
        super().__init__(receipts)
        self.lesson_rules = set()

    def projection_epoch(self):
        return repr((super().projection_epoch(), sorted(self.lesson_rules)))

    def _allows(self, values):
        resource = values["resource"]
        if resource["kind"] == "CASE_OPERATIONAL_SECTION":
            return super()._allows(values)
        if (
            values["provider_id"] != Directory.provider_id
            or values["auth_epoch"] != "epoch-1"
            or timezone.now() >= self.until
            or resource["kind"] not in {"CASE_LESSON_VERSION", "CASE_LESSON_LINK"}
        ):
            return False
        key = (
            values["subject_id"],
            values["role"],
            values["case_ref"],
            values["action"],
            resource["kind"],
            resource["target_case_id"],
            resource["version_id"],
            resource["version_sha256"],
        )
        if key not in self.lesson_rules:
            return False
        if resource["kind"] == "CASE_LESSON_LINK":
            return CaseLessonLink.objects.filter(
                pk=resource["link_id"],
                sha256=resource["link_sha256"],
                case_id=resource["case_id"],
                case__public_ref=values["case_ref"],
                lesson_version_id=resource["version_id"],
                lesson_version__lesson__series__case_id=resource["target_case_id"],
            ).exists()
        return True

    def revoke(self, *, subject="operator", action=None, case_ref=None):
        super().revoke(subject=subject, action=action, case_ref=case_ref)
        self.lesson_rules = {
            row
            for row in self.lesson_rules
            if not (
                row[0] == subject
                and (action is None or row[3] == action)
                and (case_ref is None or row[2] == case_ref)
            )
        }


class LessonDomainAuthority(ScholarlyAuthority):
    def __init__(self):
        self.rules, self.hook = set(), None

    def projection_epoch(self):
        return digest(sorted(self.rules))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        if (
            values["provider_id"] != Directory.provider_id
            or values["auth_epoch"] != "epoch-1"
            or values["kind"] != "LESSON"
        ):
            return False
        if values["action"] in {"READ_LESSON", "PROPOSE"}:
            identifier, sha256 = values["resource_id"], values["resource_sha256"]
        elif values["action"] in {"READ_LINK", "APPROVE", "REJECT", "WITHDRAW"}:
            row = (
                CaseLessonLink.objects.select_related("lesson_version")
                .filter(
                    pk=values["resource_id"],
                    sha256=values["resource_sha256"],
                    case__public_ref=values["case_ref"],
                    lesson_version__lesson__series__case__public_ref=values["target_case_ref"],
                )
                .first()
            )
            if row is None:
                return False
            identifier, sha256 = str(row.lesson_version_id), row.lesson_version.sha256
        else:
            return False
        return (
            values["subject_id"],
            values["case_ref"],
            values["target_case_ref"],
            values["action"],
            identifier,
            sha256,
        ) in self.rules


def grant_lessons(authority, domain, target, versions):
    case = Case.objects.get(pk=target["case_id"])
    for subject, role in (
        ("operator", "ORGANIZER"),
        ("admin", "ORGANIZER_ADMIN"),
        ("mufti", "MUFTI"),
    ):
        authority.grants.add(
            (subject, role, case.public_ref, "READ_LESSON_LINKS", "lesson_links", str(case.pk))
        )
        for version in versions:
            owner = Case.objects.get(pk=version.lesson.series.case_id)
            for action, operational in lesson_links.ACTION_MAP.items():
                source = owner if action == "READ_LESSON" else case
                kind = (
                    "CASE_LESSON_VERSION"
                    if action in {"READ_LESSON", "PROPOSE"}
                    else "CASE_LESSON_LINK"
                )
                authority.lesson_rules.add(
                    (
                        subject,
                        role,
                        source.public_ref,
                        operational,
                        kind,
                        str(owner.pk),
                        str(version.pk),
                        version.sha256,
                    )
                )
                domain.rules.add(
                    (
                        subject,
                        source.public_ref,
                        owner.public_ref,
                        action,
                        str(version.pk),
                        version.sha256,
                    )
                )


class LessonFixture(NoteFixture):
    def setUp(self):
        super().setUp()
        owner, common = approved("organizer-lessons-" + uuid.uuid4().hex, audio=True)
        with override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=common["provider"],
            FATWA_SCHOLARLY_LINKS_AUTHORITY=SeedAuthority(common, owner["public_ref"]),
        ):
            pins = dict(expected_revision=3, expected_evidence_version=1)
            category = scholarly.create_category(
                **common, **pins, label="دروس اصطناعية مخولة", command_id=uuid.uuid4()
            )
            series = scholarly.save_series(
                **common,
                **pins,
                title="سلسلة دروس اصطناعية محفوظة",
                teachers=[{"name": "معلم اصطناعي"}],
                command_id=uuid.uuid4(),
            )
            part = AnswerPart.objects.get(manifest__answer__case_id=owner["case_id"], ordinal=2)
            self.version = scholarly.save_lesson(
                **common,
                **pins,
                series_id=series.series_id,
                expected_series_version=series.number,
                category_id=category.pk,
                title="درس صوتي اصطناعي لربط المنظم",
                provenance="ملف اصطناعي محفوظ؛ ليس درسًا شرعيًا منشورًا",
                source_part_id=part.pk,
                command_id=uuid.uuid4(),
            )
            self.descriptive = scholarly.save_lesson(
                **common,
                **pins,
                series_id=series.series_id,
                expected_series_version=SeriesVersion.objects.filter(series=series.series)
                .latest("number")
                .number,
                category_id=category.pk,
                title="درس وصفي اصطناعي بلا تسجيل",
                provenance="وصف اصطناعي بشري بلا ملف",
                source_part_id=None,
                command_id=uuid.uuid4(),
            )
        self.receipts["lessons"] = {key: owner[key] for key in ("case_id", "public_ref")}
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor, case_keys=frozenset([*actor.case_keys, owner["public_ref"]])
            )
        self.authority, self.lesson_authority = (
            LessonAuthority(self.receipts),
            LessonDomainAuthority(),
        )
        grant_lessons(
            self.authority, self.lesson_authority, self.target, [self.version, self.descriptive]
        )
        configured = override_settings(
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.authority,
            FATWA_SCHOLARLY_LINKS_AUTHORITY=self.lesson_authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.lesson_originals = self.immutable_lesson_sources()
        self.originals = self.state()

    def immutable_lesson_sources(self):
        values = source_rows([row["case_id"] for row in self.receipts.values()])
        values.pop(CaseLessonLink._meta.db_table)
        values.pop(LinkDecision._meta.db_table)
        return digest(values)

    def lesson_values(self, **changes):
        case = Case.objects.get(pk=self.target["case_id"])
        owner = Case.objects.get(pk=self.version.lesson.series.case_id)
        return (
            dict(
                case_ref=case.public_ref,
                lesson_version_id=str(self.version.pk),
                lesson_sha256=self.version.sha256,
                reason="ربط تنظيمي بشري بالدرس المثبت",
                command_id=str(uuid.uuid4()),
                expected_revision=case.revision,
                expected_evidence_version=case.evidence_version,
                expected_target_revision=owner.revision,
                expected_target_evidence_version=owner.evidence_version,
                start_ms=10,
                end_ms=100,
            )
            | changes
        )

    def propose_lesson(self, **changes):
        with lesson_links.propose(**self.common, **self.lesson_values(**changes)) as result:
            return result

    def review_values(self, link=None, **changes):
        link = link or CaseLessonLink.objects.get(case_id=self.target["case_id"])
        case, owner = link.case, link.lesson_version.lesson.series.case
        return (
            dict(
                case_ref=case.public_ref,
                link_id=str(link.pk),
                link_sha256=link.sha256,
                action="APPROVE",
                note="مراجعة بشرية للرابط التشغيلي",
                confirmed=True,
                command_id=str(uuid.uuid4()),
                expected_sequence=link.decisions.count(),
                expected_revision=case.revision,
                expected_evidence_version=case.evidence_version,
                expected_target_revision=owner.revision,
                expected_target_evidence_version=owner.evidence_version,
            )
            | changes
        )

    def review_lesson(self, **changes):
        with lesson_links.decide(
            **{**self.common, "subject_id": "admin"}, **self.review_values(**changes)
        ) as result:
            return result
