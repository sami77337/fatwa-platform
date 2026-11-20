"""Explicit synthetic scopes, generated audio and real approved source fixtures."""

import io
import uuid
import wave
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.answer_media import services as answer_media
from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority as PublicationAuthority
from apps.experimental_publication.tests import Directory
from apps.library_preview.policy import PreviewPolicy, PublicationGrant
from apps.research_library.test_support import bind_identity_snapshot
from apps.source_rights.tests import Authority as SourceAuthority
from apps.timed_citations.rights import TimedMediaRights
from tests.casework.test_http import WEB_SETTINGS

from . import services
from .authority import AnswerMediaAuthority

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
    "FATWA_PUBLIC_ANSWER_MEDIA_ENABLED": True,
    "FATWA_PUBLIC_ANSWER_MEDIA_PUBLIC_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
    "FATWA_LIBRARY_PREVIEW_ENABLED": True,
    "FATWA_CASE_CITATIONS_ENABLED": True,
    "FATWA_KNOWLEDGE_LINKS_ENABLED": True,
    "FATWA_SOURCE_RIGHTS_ENFORCED": True,
    "FATWA_SOURCE_RIGHTS_ENABLED": True,
    "MIDDLEWARE": [
        "apps.library_preview.guard.PreviewCompositionGuard",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
}
CREDENTIALS = {
    "editor": "synthetic-editor-credential-32-characters",
    "other": "synthetic-reviewer-credential-32-characters",
    "publisher": "synthetic-publisher-credential-32-characters",
}
TEXT = "هذا تفريغ اصطناعي أول. وهذا مقطع اصطناعي ثان للمراجعة."


def audio():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\x00\x00" * 48000)
    return output.getvalue()


class FixtureAuthority(AnswerMediaAuthority):
    def __init__(self, ref):
        self.ref, self.denied, self.hook = ref, set(), None

    def projection_epoch(self):
        return repr((self.ref, sorted(self.denied, key=repr)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["case_ref"] == self.ref
            and values["provider_id"] == Directory.provider_id
            and values["auth_epoch"] == "epoch-1"
            and values["subject_id"] in CREDENTIALS
            and values["action"] not in self.denied
            and (values["subject_id"], values["action"]) not in self.denied
        )


class FixtureMediaRights(TimedMediaRights):
    def __init__(self, ref):
        self.ref, self.pins, self.denied, self.hook = ref, set(), set(), None
        self.until = timezone.now() + timedelta(minutes=30)

    def projection_epoch(self):
        return self.media_projection_epoch()

    def media_projection_epoch(self):
        return repr(
            (self.ref, sorted(self.pins), sorted(self.denied, key=repr), self.until.isoformat())
        )

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        r = values["resource"]
        return (
            values["case_ref"] == self.ref
            and values["provider_id"] == Directory.provider_id
            and values["auth_epoch"] == "epoch-1"
            and values["subject_id"] in CREDENTIALS
            and values["action"] == "READ_MEDIA"
            and values["subject_id"] not in self.denied
            and timezone.now() < self.until
            and (r.kind, r.identifier, r.sha256) in self.pins
        )

    def grant_deadline(self, **values):
        return self.until if self.permits(**values) else None


class MediaFixture:
    def setUp(self):
        super().setUp()
        identifier = uuid.uuid4().hex
        self.receipt = cases.intake_case(
            original_question="PRIVATE requester question synthetic",
            source_event_id=identifier,
            requester_id="private-" + identifier,
            idempotency_key=identifier,
            synthetic_fixtures_only=True,
        )
        self.directory = bind_identity_snapshot(Directory([self.receipt["public_ref"]]))
        self.directory.authenticate = lambda credential: self.directory.resolve(
            next((subject for subject, value in CREDENTIALS.items() if value == credential), "")
        )
        self.authority = FixtureAuthority(self.receipt["public_ref"])
        self.rights = FixtureMediaRights(self.receipt["public_ref"])
        self.configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY=self.authority,
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=PublicationAuthority(
                self.receipt["public_ref"]
            ),
            FATWA_SOURCE_RIGHTS_AUTHORITY=SourceAuthority(self.receipt["public_ref"]),
        )
        self.configured.enable()
        self.addCleanup(self.configured.disable)
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        result = answer_media.save_multipart_answer(
            **self.common,
            text="جواب اصطناعي محفوظ لا يفتي في مسألة",
            files=[
                {"raw": audio(), "filename": "private-original-name.wav", "media_type": "audio/wav"}
            ],
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.answer_id = result["answers"][-1]["id"]
        cases.record_decision(
            **self.common,
            answer_id=self.answer_id,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        self.part = AnswerPart.objects.get(manifest__answer_id=self.answer_id, kind="AUDIO")
        self.rights.pins.add(("ANSWER_MEDIA", str(self.part.pk), self.part.sha256))
        self.edition = publication.create_edition(
            **self.common,
            title="جواب تجريبي منشور",
            category="موضوع اصطناعي",
            body="النص المنشور السليم مستقل عن المرفق الاختياري.",
            expected_revision=3,
            expected_evidence_version=1,
        )
        publication.act(
            **{**self.common, "subject_id": "other"},
            edition_id=self.edition["id"],
            action="REVIEW",
            reviewed=True,
        )
        publication.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=self.edition["id"],
            action="APPROVE",
        )
        self.publication = PublicationEdition.objects.get(pk=self.edition["id"])
        self.preview_policy = PreviewPolicy(
            (PublicationGrant(str(self.publication.pk), self.publication.content_sha256),),
            (),
            timezone.now() + timedelta(minutes=30),
            True,
        )
        configured = override_settings(FATWA_LIBRARY_PREVIEW_POLICY=self.preview_policy)
        configured.enable()
        self.addCleanup(configured.disable)
        self.pins = dict(self.common, expected_revision=3, expected_evidence_version=1)

    def save(self, **changes):
        values = dict(
            self.pins,
            part_id=str(self.part.pk),
            text=TEXT,
            segments=[{"char_start": 0, "char_end": 21, "start_ms": 1000, "end_ms": 2500}],
            change_kind="EDITORIAL",
            note="تصحيح اصطناعي بعد الاستماع",
            expected_version=0,
            request_key=uuid.uuid4(),
        )
        return services.save_transcript(**{**values, **changes})

    def review(self, row, **changes):
        values = dict(
            self.pins,
            subject_id="other",
            transcript_id=row["id"],
            action="REVIEW",
            note="مراجعة مستقلة للتفريغ والوقت",
            confirmed=True,
            expected_actions=row["action_count"],
            request_key=uuid.uuid4(),
        )
        return services.review_transcript(**{**values, **changes})

    def prepare(self, transcript=None, **changes):
        values = dict(
            self.pins,
            publication_id=str(self.publication.pk),
            part_id=str(self.part.pk),
            transcript_id=transcript["id"] if transcript else None,
            label="تسجيل الجواب الاصطناعي",
            note="مرشح إتاحة المحتوى المحدد وحقوقه",
            expected_version=0,
            request_key=uuid.uuid4(),
        )
        return services.prepare_media(**{**values, **changes})

    def decide(self, row, action, **changes):
        values = dict(
            self.pins,
            subject_id="other" if action == "REVIEW" else "publisher",
            edition_id=row["id"],
            action=action,
            note="مراجعة بشرية مستقلة للإتاحة",
            confirmed=True,
            expected_actions=row["action_count"],
            minutes=15 if action == "RELEASE" else 0,
            request_key=uuid.uuid4(),
        )
        return services.review_media(**{**values, **changes})

    def release(self, transcript=None, **changes):
        return self.decide(self.decide(self.prepare(transcript, **changes), "REVIEW"), "RELEASE")
