"""Current library approvals and an actual human-reviewed transcript are preserved."""

import uuid

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.public_answer_media import test_support as recording_fixtures
from apps.public_answer_media.models import (
    PublicMediaAction,
    PublicMediaEdition,
    RecordingTranscript,
    TranscriptAction,
)
from apps.research_library import test_support as library_fixtures
from apps.research_library.models import LibraryBlob, LibraryDecision, LibraryVersion
from apps.upload_security.test_support import configure_scanner

from . import execution, services
from .models import DerivedOutput
from .sources import Source
from .test_execution import picture, recording
from .test_support import FEATURES, Authority


@override_settings(**{**library_fixtures.FEATURES, **FEATURES})
class LibraryDerivativeTests(library_fixtures.LibraryFixture, TransactionTestCase):
    def setUp(self):
        configure_scanner(self)
        super().setUp()
        configured = override_settings(
            FATWA_MEDIA_DERIVATIVES_AUTHORITY=Authority(self.receipt["public_ref"]),
            FATWA_MEDIA_DERIVATIVES_PROCESSOR=execution.FFmpegProcessor(
                "/usr/bin/ffmpeg", "/usr/bin/ffprobe"
            ),
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def prepare_job(self, row, task):
        return services.prepare(
            **self.common,
            source=Source("LIBRARY_VERSION", row["version_id"]),
            task=task,
            expected_revision=1,
            expected_evidence_version=1,
            request_key=uuid.uuid4(),
        )

    def test_approved_audio_and_image_versions_get_actual_separate_outputs(self):
        for raw, name, media_type, task in (
            (recording(), "original.wav", "audio/wav", "AUDIO_PLAYBACK"),
            (picture(), "original.png", "image/png", "THUMBNAIL"),
            (library_fixtures.video(), "original.webm", "video/webm", "THUMBNAIL"),
        ):
            with self.subTest(task=task, media_type=media_type):
                row = self.write(
                    payload=library_fixtures.payload(
                        {"audio": "AUDIO", "image": "IMAGE", "video": "VIDEO"}[
                            media_type.split("/")[0]
                        ]
                    ),
                    file_bytes=raw,
                    filename=name,
                    media_type=media_type,
                )
                self.approve(row, uses=["READ"])
                original = [
                    list(model.objects.order_by("pk").values())
                    for model in (LibraryBlob, LibraryVersion, LibraryDecision)
                ]
                job = self.prepare_job(row, task)
                ready = services.run_job(**self.common, job_id=job["id"])
                self.assertEqual(ready["state"], "READY", ready)
                self.assertEqual(services.original(**self.common, job_id=job["id"])["raw"], raw)
                output = services.read_output(**self.common, job_id=job["id"])
                self.assertEqual(output["engine"]["mode"], "LOCAL_FFMPEG")
                with self.assertRaises(cases.CaseConflict):
                    services.download(**self.common, job_id=job["id"])
                self.assertEqual(
                    original,
                    [
                        list(model.objects.order_by("pk").values())
                        for model in (LibraryBlob, LibraryVersion, LibraryDecision)
                    ],
                )

    def test_library_read_approval_is_required_before_queue_or_worker(self):
        row = self.write(
            payload=library_fixtures.payload("AUDIO"),
            file_bytes=recording(),
            filename="original.wav",
            media_type="audio/wav",
        )
        with self.assertRaises(cases.CaseConflict):
            self.prepare_job(row, "AUDIO_PLAYBACK")
        self.approve(row, uses=["CITE"])
        with self.assertRaises(cases.CaseConflict):
            self.prepare_job(row, "AUDIO_PLAYBACK")
        self.assertEqual(DerivedOutput.objects.count(), 0)


@override_settings(**{**recording_fixtures.FEATURES, **FEATURES})
class HumanTranscriptPreservationTests(recording_fixtures.MediaFixture, TransactionTestCase):
    def setUp(self):
        configure_scanner(self)
        super().setUp()
        configured = override_settings(
            FATWA_MEDIA_DERIVATIVES_AUTHORITY=Authority(self.receipt["public_ref"]),
            FATWA_MEDIA_DERIVATIVES_PROCESSOR=execution.FFmpegProcessor(
                "/usr/bin/ffmpeg", "/usr/bin/ffprobe"
            ),
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def test_processing_retry_does_not_discard_reviewed_transcript_or_public_exact_pin(self):
        reviewed = self.review(self.save())
        self.release(reviewed)
        models = (RecordingTranscript, TranscriptAction, PublicMediaEdition, PublicMediaAction)
        original = [list(model.objects.order_by("pk").values()) for model in models]
        self.assertTrue(all(original))
        job = services.prepare(
            **self.common,
            source=Source("ANSWER_PART", str(self.part.pk)),
            task="AUDIO_PLAYBACK",
            request_key=uuid.uuid4(),
            expected_revision=3,
            expected_evidence_version=1,
        )
        with override_settings(FATWA_MEDIA_DERIVATIVES_PROCESSOR=None):
            failed = services.run_job(**self.common, job_id=job["id"])
        self.assertEqual(failed["state"], "UNAVAILABLE")
        self.assertEqual(
            services.original(**self.common, job_id=job["id"])["raw"], recording_fixtures.audio()
        )
        retried = services.command(
            **self.common,
            job_id=job["id"],
            action="RETRY",
            expected_sequence=failed["sequence"],
            request_key=uuid.uuid4(),
        )
        self.assertEqual(services.run_job(**self.common, job_id=retried["id"])["state"], "READY")
        self.assertEqual(
            original, [list(model.objects.order_by("pk").values()) for model in models]
        )
