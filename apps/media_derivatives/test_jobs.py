"""Real PostgreSQL + ffmpeg, canonical histories, current rights and late revocation."""

import io
import json
import time
import uuid
from dataclasses import replace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase, override_settings

from apps.answer_media.models import AnswerPart
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseDecision, CaseEvent, CaseEvidence
from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.public_answer_media.models import RecordingTranscript, TranscriptAction

from . import execution, policy, services
from .models import DerivativeEvent, DerivativeJob, DerivedOutput
from .sources import Source
from .test_support import FEATURES, DerivativeFixture


@override_settings(**FEATURES)
class DerivativeJobTests(DerivativeFixture, TransactionTestCase):
    def originals(self):
        return [
            list(model.objects.order_by("pk").values())
            for model in (
                CaseAttachment,
                AnswerPart,
                AnswerRevision,
                CaseEvidence,
                CaseEvent,
                CaseDecision,
                RecordingTranscript,
                TranscriptAction,
                PublicationEdition,
                PublicationAction,
            )
        ]

    def test_actual_worker_runs_outside_locks_and_derivative_is_separate_from_original(self):
        before = self.originals()
        job = self.prepare()
        self.assertEqual(job["state"], "QUEUED")
        actual = execution.FFmpegProcessor.run
        calls = []

        def run(processor, *args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            calls.append(True)
            return actual(processor, *args, **kwargs)

        with patch.object(execution.FFmpegProcessor, "run", run):
            completed = self.execute(job)
        self.assertEqual(completed["state"], "READY")
        self.assertEqual(calls, [True])
        self.assertEqual(DerivedOutput.objects.count(), 1)
        output = services.download(**self.common, job_id=job["id"])
        self.assertEqual(output["raw"], self.raw)
        self.assertEqual(output["engine"]["mode"], "LOCAL_FFMPEG")
        self.assertEqual(services.original(**self.common, job_id=job["id"])["raw"], self.raw)
        self.assertEqual(self.originals(), before)

    def test_answer_part_uses_its_exact_owner_without_touching_transcript_or_decisions(self):
        before = self.originals()
        completed = self.execute(self.prepare(source=Source("ANSWER_PART", str(self.part.pk))))
        self.assertEqual(completed["state"], "READY")
        stored = DerivativeJob.objects.get(pk=completed["id"])
        self.assertEqual(stored.answer_part_id, self.part.pk)
        self.assertIsNone(stored.attachment_id)
        self.assertEqual(self.originals(), before)

    def test_missing_processor_is_recorded_unavailable_and_original_remains_readable(self):
        before = self.originals()
        with override_settings(FATWA_MEDIA_DERIVATIVES_PROCESSOR=None):
            completed = self.execute(self.prepare())
            self.assertEqual(
                (completed["state"], completed["code"]), ("UNAVAILABLE", "PROCESSOR_UNAVAILABLE")
            )
            self.assertEqual(
                services.original(**self.common, job_id=completed["id"])["raw"], self.raw
            )
        self.assertEqual(DerivedOutput.objects.count(), 0)
        retried = self.control(completed, "RETRY")
        self.assertEqual(self.execute(retried)["state"], "READY")
        self.assertEqual(
            [row.action for row in DerivativeEvent.objects.order_by("sequence")],
            ["CREATE", "CLAIM", "FAIL", "RETRY", "CLAIM", "COMPLETE"],
        )
        self.assertEqual(self.originals(), before)

    def test_unavailable_asr_is_not_a_queue_or_a_transcript_write(self):
        before = self.originals()
        with self.assertRaises(cases.CaseConflict):
            self.prepare(task="TRANSCRIPT")
        self.assertEqual(DerivativeJob.objects.count(), 0)
        self.assertEqual(self.originals(), before)

    def test_create_execute_read_retry_cancel_are_independent_grants(self):
        self.authority.denied.add("CREATE")
        with self.assertRaises(cases.CaseConflict):
            self.prepare()
        self.authority.denied.clear()
        job = self.prepare()
        self.authority.denied.add("EXECUTE")
        with self.assertRaises(cases.CaseConflict):
            self.execute(job)
        self.assertEqual(DerivativeEvent.objects.count(), 1)
        self.authority.denied = {"CANCEL"}
        with self.assertRaises(cases.CaseConflict):
            self.control(job, "CANCEL")
        self.authority.denied = {"READ"}
        with self.assertRaises(cases.CaseConflict):
            services.status(**self.common, job_id=job["id"])
        self.authority.denied.clear()
        self.assertEqual(self.execute(job)["state"], "READY")
        self.authority.denied.add("READ")
        with self.assertRaises(cases.CaseConflict):
            services.download(**self.common, job_id=job["id"])

    def test_source_read_and_clean_scan_remain_independent_after_ready(self):
        job = self.execute(self.prepare())
        self.rights.denied.add(("ATTACHMENT", "READ_MEDIA"))
        with self.assertRaises(cases.CaseConflict):
            services.download(**self.common, job_id=job["id"])
        self.rights.denied.clear()
        spec = self.scanner.current
        self.scanner.current = replace(spec, signature_version="SYNTHETIC-revoked")
        with self.assertRaises(cases.CaseConflict):
            services.download(**self.common, job_id=job["id"])
        self.scanner.current = spec
        self.assertEqual(services.download(**self.common, job_id=job["id"])["raw"], self.raw)

    def test_cancel_queued_job_never_starts_engine_and_cannot_retry_cancelled(self):
        job = self.control(self.prepare(), "CANCEL")
        self.assertEqual(job["state"], "CANCELLED")
        with patch.object(execution.FFmpegProcessor, "run") as child:
            with self.assertRaises(cases.CaseConflict):
                self.execute(job)
        child.assert_not_called()
        with self.assertRaises(cases.CaseConflict):
            self.control(job, "RETRY")
        self.assertEqual(DerivedOutput.objects.count(), 0)

    def test_cancel_during_actual_processing_discards_a_late_valid_result(self):
        job = self.prepare()
        actual = execution.FFmpegProcessor.run

        def run(processor, *args, **kwargs):
            result = actual(processor, *args, **kwargs)
            running = services.status(**self.common, job_id=job["id"])
            self.control(running, "CANCEL")
            return result

        with patch.object(execution.FFmpegProcessor, "run", run):
            self.assertEqual(self.execute(job)["state"], "CANCELLED")
        self.assertEqual(DerivedOutput.objects.count(), 0)

    def test_revocation_after_decoder_before_save_discards_result(self):
        actual = execution.FFmpegProcessor.run
        job = self.prepare()

        def run(processor, *args, **kwargs):
            result = actual(processor, *args, **kwargs)
            self.rights.denied.add(("ATTACHMENT", "READ_MEDIA"))
            return result

        with patch.object(execution.FFmpegProcessor, "run", run):
            with self.assertRaises(cases.CaseConflict):
                self.execute(job)
        self.assertEqual(DerivedOutput.objects.count(), 0)
        self.assertEqual(job["source"]["sha256"], self.attachment["sha256"])

    def test_final_authorizer_cannot_save_after_scan_was_withdrawn(self):
        job = self.prepare()
        observed = []

        def revoke(values):
            if DerivedOutput.objects.exists():
                observed.append(True)
                self.scanner.current = replace(
                    self.scanner.current, signature_version="SYNTHETIC-final-denial"
                )

        self.authority.hook = revoke
        with self.assertRaises(cases.CaseConflict):
            self.execute(job)
        self.assertTrue(observed)
        self.assertEqual(DerivedOutput.objects.count(), 0)
        self.assertEqual(DerivativeEvent.objects.filter(state="READY").count(), 0)

    def test_request_idempotency_compare_and_swap_and_foreign_owner_denial(self):
        key = uuid.uuid4()
        job = self.prepare(request_key=key)
        self.assertEqual(self.prepare(request_key=key)["id"], job["id"])
        with self.assertRaises(cases.CaseConflict):
            self.prepare(request_key=key, source=Source("ANSWER_PART", str(self.part.pk)))
        with self.assertRaises(cases.CaseConflict):
            self.control(job, "CANCEL", expected_sequence=2)
        with self.assertRaises(cases.CaseConflict):
            services.status(**{**self.common, "subject_id": "other"}, job_id=job["id"])
        self.assertEqual(DerivativeJob.objects.count(), 1)

    def test_default_off_missing_authority_and_outer_transaction_cannot_process(self):
        for settings in (
            {"FATWA_MEDIA_DERIVATIVES_ENABLED": False},
            {"FATWA_MEDIA_DERIVATIVES_AUTHORITY": None},
        ):
            with override_settings(**settings), self.assertRaises(cases.CaseConflict):
                self.prepare()
        job = self.prepare()
        with transaction.atomic(), self.assertRaises(cases.CaseConflict):
            self.execute(job)
        self.assertEqual(DerivativeEvent.objects.count(), 1)

    def test_history_and_bytes_cannot_be_updated_deleted_or_forged(self):
        job = self.execute(self.prepare())
        for model, field, value in (
            (DerivativeJob, "task", "THUMBNAIL"),
            (DerivativeEvent, "state", "READY"),
            (DerivedOutput, "raw", b"changed"),
        ):
            with (
                self.subTest(model=model.__name__),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
            ):
                model.objects.update(**{field: value})
            with (
                self.subTest(delete=model.__name__),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
            ):
                with connection.cursor() as cursor:
                    cursor.execute('DELETE FROM "' + model._meta.db_table + '"')
        self.assertEqual(services.download(**self.common, job_id=job["id"])["raw"], self.raw)

    def test_independent_worker_command_requires_a_configured_current_directory(self):
        job = self.prepare()
        with self.assertRaises(CommandError):
            call_command(
                "process_media_derivative",
                job=job["id"],
                synthetic_fixtures_only=True,
                stdout=io.StringIO(),
            )
        output = io.StringIO()
        with override_settings(FATWA_MEDIA_DERIVATIVES_WORKER_DIRECTORY=self.directory):
            call_command(
                "process_media_derivative",
                job=job["id"],
                synthetic_fixtures_only=True,
                stdout=output,
            )
        report = json.loads(output.getvalue())
        self.assertEqual(report["jobs"], [{"job": job["id"], "state": "READY", "code": "READY"}])
        self.assertNotIn(self.raw.hex(), output.getvalue())

    def test_expired_lease_requires_explicit_retry_and_old_attempt_cannot_complete(self):
        job = self.prepare()
        with policy.boundary(**self.common) as guard:
            stored = services._job(guard, job["id"])
            services._read(guard, stored, "EXECUTE")
            with patch.object(services, "LEASE_SECONDS", 0.02):
                old = services._claim(guard, stored)
        time.sleep(0.03)
        status = services.status(**self.common, job_id=job["id"])
        self.assertEqual(status["state"], "EXPIRED")
        with self.assertRaises(cases.CaseConflict):
            self.execute(status)
        retried = self.control(status, "RETRY")
        ready = self.execute(retried)
        self.assertEqual((ready["state"], ready["attempt"]), ("READY", 2))
        output = DerivedOutput.objects.get(job_id=job["id"])
        self.assertNotEqual(output.lease, old.lease)
        with self.assertRaises(DatabaseError), transaction.atomic():
            from .ledger import seal

            duplicate = DerivedOutput(
                job=stored,
                attempt=old.attempt,
                lease=old.lease,
                source_digest=stored.source_digest,
                recipe_version=stored.recipe_version,
                sha256=output.sha256,
                size=output.size,
                raw=bytes(output.raw),
                media_type=output.media_type,
                metadata=output.metadata,
                engine=output.engine,
            )
            seal(duplicate)

    def test_only_one_current_database_lease_and_four_explicit_attempts(self):
        first, second = self.prepare(), self.prepare()
        with policy.boundary(**self.common) as guard:
            stored = services._job(guard, first["id"])
            services._read(guard, stored, "EXECUTE")
            services._claim(guard, stored)
        with self.assertRaises(cases.CaseConflict):
            self.execute(second)
        self.control(services.status(**self.common, job_id=first["id"]), "CANCEL")
        with override_settings(FATWA_MEDIA_DERIVATIVES_PROCESSOR=None):
            current = second
            for attempt in range(1, 5):
                current = self.execute(current)
                self.assertEqual((current["attempt"], current["state"]), (attempt, "UNAVAILABLE"))
                if attempt < 4:
                    current = self.control(current, "RETRY")
            with self.assertRaises(cases.CaseConflict):
                self.control(current, "RETRY")
        self.assertEqual(DerivedOutput.objects.count(), 0)

    def test_inline_read_never_implies_derivative_download_or_source_export(self):
        job = self.execute(self.prepare())
        self.assertEqual(services.read_output(**self.common, job_id=job["id"])["raw"], self.raw)
        self.authority.denied.add("DOWNLOAD")
        with self.assertRaises(cases.CaseConflict):
            services.download(**self.common, job_id=job["id"])
        self.authority.denied.clear()
        self.export_authority.denied.add(("EXPORT_MEDIA", "ATTACHMENT"))
        with self.assertRaises(cases.CaseConflict):
            services.download(**self.common, job_id=job["id"])
        self.assertEqual(services.read_output(**self.common, job_id=job["id"])["raw"], self.raw)
        self.export_authority.denied.clear()
        self.assertEqual(services.download(**self.common, job_id=job["id"])["raw"], self.raw)
