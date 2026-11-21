"""Generated media, explicit fixture grants, real originals and real ffmpeg."""

import uuid
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.answer_media import services as answers
from apps.answer_media.models import AnswerPart
from apps.case_attachments import services as attachments
from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot
from apps.research_workspace.tests import SyntheticRights
from apps.selected_exports.tests import FixtureExportAuthority
from apps.upload_security.test_support import configure_scanner
from config.settings import campaign_review
from tests.casework.test_http import WEB_SETTINGS

from . import execution, services
from .authority import DerivativeAuthority
from .sources import Source
from .test_execution import recording

FEATURES = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_MEDIA_DERIVATIVES_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_VIDEO_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_RESEARCH_LIBRARY_ENABLED": True,
    "FATWA_DATA_PRIVACY_ENABLED": False,
    "MIDDLEWARE": list(
        dict.fromkeys(
            [
                *campaign_review.MIDDLEWARE,
                "apps.media_derivatives.policy.DerivativeResponses",
            ]
        )
    ),
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
}


class Authority(DerivativeAuthority):
    def __init__(self, ref):
        self.ref, self.denied, self.hook = ref, set(), None
        self.until = timezone.now() + timedelta(minutes=30)

    def projection_epoch(self):
        return repr((self.ref, sorted(self.denied, key=repr), self.until))

    def grant_deadline(self, **values):
        return self.until

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == Directory.provider_id
            and values["subject_id"] == "editor"
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] == self.ref
            and values["task"] in execution.TASKS
            and values["action"] in {"CREATE", "EXECUTE", "READ", "DOWNLOAD", "CANCEL", "RETRY"}
            and values["action"] not in self.denied
            and (values["source"]["kind"], values["action"]) not in self.denied
            and timezone.now() < self.until
        )


class DerivativeFixture:
    def setUp(self):
        super().setUp()
        key = uuid.uuid4().hex
        self.receipt = cases.intake_case(
            original_question="PRIVATE synthetic derivative case",
            source_event_id=key,
            requester_id="requester-" + key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        self.directory = bind_identity_snapshot(Directory([self.receipt["public_ref"]]))
        self.directory.authenticate = lambda credential: (
            self.directory.resolve("editor")
            if credential == "synthetic-editor-credential-32-characters"
            else None
        )
        self.authority = Authority(self.receipt["public_ref"])
        self.rights = SyntheticRights(self.receipt["public_ref"])
        self.export_authority = FixtureExportAuthority(self.receipt["public_ref"])
        self.processor = execution.FFmpegProcessor("/usr/bin/ffmpeg", "/usr/bin/ffprobe")
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_MEDIA_DERIVATIVES_AUTHORITY=self.authority,
            FATWA_MEDIA_DERIVATIVES_PROCESSOR=self.processor,
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            FATWA_SELECTED_EXPORTS_AUTHORITY=self.export_authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        configure_scanner(self)
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.raw = recording()
        self.attachment = attachments.upload(
            token=self.receipt["token"],
            raw=self.raw,
            filename="private-original.wav",
            media_type="audio/wav",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        saved = answers.save_multipart_answer(
            **self.common,
            text="PRIVATE unchanged synthetic answer",
            files=[
                {"raw": self.raw, "filename": "authored-original.wav", "media_type": "audio/wav"}
            ],
            expected_revision=2,
            expected_evidence_version=2,
        )
        self.part = AnswerPart.objects.get(
            manifest__answer_id=saved["answers"][-1]["id"], ordinal=2
        )
        self.source = Source("ATTACHMENT", self.attachment["id"])

    def prepare(self, **changes):
        case = Case.objects.get(pk=self.common["case_id"])
        values = dict(
            source=self.source,
            task="AUDIO_PLAYBACK",
            request_key=uuid.uuid4(),
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        return services.prepare(**self.common, **{**values, **changes})

    def execute(self, job):
        return services.run_job(**self.common, job_id=job["id"])

    def control(self, job, action, **changes):
        return services.command(
            **self.common,
            job_id=job["id"],
            action=action,
            **{"request_key": uuid.uuid4(), "expected_sequence": job["sequence"], **changes},
        )
