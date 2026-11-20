"""Real PostgreSQL source, concurrency, policy and immutable-history regressions."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent
from apps.experimental_publication import services as publication
from apps.library_preview import services as preview

from . import public, services
from .boundaries import assert_snapshot
from .models import PublicMediaAction, PublicMediaEdition, RecordingTranscript, TranscriptAction
from .test_support import FEATURES, TEXT, MediaFixture, audio


@override_settings(**FEATURES)
class MediaTests(MediaFixture, TransactionTestCase):
    def test_all_mutations_require_exact_case_and_evidence_pins(self):
        for changes in (
            {"expected_revision": None},
            {"expected_evidence_version": None},
            {"expected_revision": True},
            {"expected_revision": 2},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.save(**changes)
        self.assertFalse(RecordingTranscript.objects.exists())

    def test_sql_cannot_release_an_edition_after_its_publication_was_withdrawn(self):
        row = self.decide(self.prepare(), "REVIEW")
        edition = PublicMediaEdition.objects.get(pk=row["id"])
        prior = edition.actions.get(action="REVIEW")
        publication.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=str(self.publication.pk),
            action="WITHDRAW",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                services._seal(
                    PublicMediaAction(
                        edition=edition,
                        sequence=2,
                        previous_digest=prior.digest,
                        action="RELEASE",
                        note="forged release of withdrawn text",
                        valid_until=timezone.now() + timedelta(minutes=5),
                        subject_id="publisher",
                        provider_id=edition.provider_id,
                        auth_epoch="epoch-1",
                        case_revision=3,
                        evidence_version=1,
                        request_key=uuid.uuid4(),
                        request_sha256="c" * 64,
                    )
                )

    def test_exact_revision_review_release_optional_transcript_and_segments(self):
        before = list(CaseEvent.objects.values())
        first = self.save()
        with self.assertRaises(cases.CaseConflict):
            self.prepare(first)
        reviewed = self.review(first)
        released = self.release(reviewed)
        with public.publication_projection(self.publication.pk) as result:
            self.assertEqual(result["publication"]["body"], self.publication.body)
            self.assertEqual(result["recordings"][0]["text"], TEXT)
            self.assertEqual(result["files"][released["id"]]["raw"], audio())
            self.assertNotIn("private-original", result["files"][released["id"]]["filename"])
        with services.segment_projection(
            **self.common, transcript_id=first["id"], index=0
        ) as segment:
            self.assertEqual(segment["text"], TEXT[:21])
            self.assertTrue(segment["audio_url"].endswith("#t=1,2.5"))
        self.assertEqual(list(CaseEvent.objects.values()), before)
        self.assertEqual(Case.objects.get(pk=self.receipt["case_id"]).revision, 3)
        self.assertEqual(bytes(AnswerPart.objects.get(pk=self.part.pk).original), audio())

    def test_new_meaning_revision_loses_review_and_preserves_first_and_public_exact_pin(self):
        first = self.review(self.save())
        self.release(first)
        second = self.save(
            text="تصحيح جديد يحتاج إلى مراجعة المعنى",
            segments=[],
            change_kind="MEANING_REVIEW",
            expected_version=1,
        )
        with self.assertRaises(cases.CaseConflict):
            self.review(second)
        with self.assertRaises(cases.CaseConflict):
            self.review(second, action="APPROVE_MEANING", subject_id="editor")
        with self.assertRaises(cases.CaseConflict):
            self.prepare(second, expected_version=1)
        with public.publication_projection(self.publication.pk) as result:
            self.assertEqual(result["recordings"][0]["text"], TEXT)
        self.authority.denied.add("REVIEW_MEANING")
        with self.assertRaises(cases.CaseConflict):
            self.review(second, action="APPROVE_MEANING")
        self.authority.denied.clear()
        approved = self.review(second, action="APPROVE_MEANING")
        self.release(approved, expected_version=1)
        with public.publication_projection(self.publication.pk) as result:
            self.assertEqual(result["recordings"][0]["text"], second["text"])
            self.assertEqual(result["recordings"][0]["segments"], [])
        self.assertEqual(RecordingTranscript.objects.get(pk=first["id"]).text, TEXT)

    def test_audio_only_release_does_not_invent_transcript(self):
        released = self.release()
        with public.recording_projection(released["id"]) as result:
            self.assertEqual(result["file"]["raw"], audio())
            self.assertEqual(result["recording"]["text"], "")
            self.assertFalse(result["recording"]["transcript_reviewed"])
            self.assertEqual(result["recording"]["segments"], [])

    def test_separate_rights_default_flags_roles_scope_and_epoch_deny(self):
        first = self.review(self.save())
        released = self.release(first)
        for changes in (
            {"FATWA_PUBLIC_ANSWER_MEDIA_ENABLED": False},
            {"FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY": None},
            {"FATWA_RESEARCH_WORKSPACE_RIGHTS": None},
        ):
            with override_settings(**changes), self.assertRaises(cases.CaseConflict):
                with services.transcript_projection(**self.common, transcript_id=first["id"]):
                    pass
        for field, value in (
            ("role", "ORGANIZER_ADMIN"),
            ("active", False),
            ("case_keys", frozenset()),
            ("auth_epoch", "epoch-2"),
        ):
            before = self.directory.identities["other"]
            self.directory.identities["other"] = replace(before, **{field: value})
            with self.assertRaises(preview.PreviewUnavailable):
                with public.recording_projection(released["id"]):
                    pass
            self.directory.identities["other"] = before
        self.authority.denied.add("PUBLIC_TRANSCRIPT")
        with self.assertRaises(preview.PreviewUnavailable):
            with public.recording_projection(released["id"]):
                pass
        self.authority.denied.clear()
        self.rights.denied.add("publisher")
        with self.assertRaises(preview.PreviewUnavailable):
            with public.recording_projection(released["id"]):
                pass

    def test_idempotency_conflict_and_cas_do_not_create_second_record(self):
        key = uuid.uuid4()
        first = self.save(request_key=key)
        self.assertEqual(self.save(request_key=key)["id"], first["id"])
        with self.assertRaises(cases.CaseConflict):
            self.save(request_key=key, text="مختلف", segments=[])
        with self.assertRaises(cases.CaseConflict):
            self.save(expected_version=0)
        key = uuid.uuid4()
        self.review(first, request_key=key)
        self.assertEqual(self.review(first, request_key=key)["action_count"], 1)
        with self.assertRaises(cases.CaseConflict):
            self.review(first)
        self.assertEqual(RecordingTranscript.objects.count(), 1)
        self.assertEqual(TranscriptAction.objects.count(), 1)

    def test_segments_need_exact_order_text_and_real_duration(self):
        for segment in (
            {"char_start": 0, "char_end": 1000, "start_ms": 1, "end_ms": 2},
            {"char_start": 0, "char_end": 1, "start_ms": 2, "end_ms": 1},
            {"char_start": 0, "char_end": 1, "start_ms": 1, "end_ms": 6001},
            {"char_start": True, "char_end": 1, "start_ms": 1, "end_ms": 2},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.save(segments=[segment])
        first = self.review(self.save(segments=[]))
        with services.search_projection(**self.common) as result:
            self.assertEqual(result["rows"], [])
        with self.assertRaises(cases.CaseConflict):
            with services.segment_projection(**self.common, transcript_id=first["id"], index=0):
                pass

    def test_all_four_tables_are_sql_append_only_and_seal_checked(self):
        self.release(self.review(self.save()))
        for model in (RecordingTranscript, TranscriptAction, PublicMediaEdition, PublicMediaAction):
            row = model.objects.first()
            for operation in ("update", "delete"):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        if operation == "update":
                            model.objects.all().update(note="changed")
                        else:
                            with connection.cursor() as cursor:
                                cursor.execute(
                                    f"DELETE FROM {connection.ops.quote_name(model._meta.db_table)} WHERE id=%s",
                                    [row.pk],
                                )
            values = {
                field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields
            }
            values.update(id=uuid.uuid4(), request_key=uuid.uuid4(), note="unsealed")
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    model.objects.create(**values)

    def test_public_media_review_and_release_must_be_independent(self):
        row = self.prepare()
        with self.assertRaises(cases.CaseConflict):
            self.decide(row, "RELEASE")
        with self.assertRaises(cases.CaseConflict):
            self.decide(row, "REVIEW", subject_id="editor")
        reviewed = self.decide(row, "REVIEW")
        for actor in ("editor", "other"):
            with self.assertRaises(cases.CaseConflict):
                self.decide(reviewed, "RELEASE", subject_id=actor)
        with self.assertRaises(cases.CaseConflict):
            self.decide(reviewed, "RELEASE", minutes=61)

    def test_withdrawal_does_not_resurrect_prior_release(self):
        first = self.release()
        second = self.release(expected_version=1)
        self.decide(second, "WITHDRAW")
        with self.assertRaises(preview.PreviewUnavailable):
            with public.recording_projection(first["id"]):
                pass
        with self.assertRaises(preview.PreviewUnavailable):
            with public.recording_projection(second["id"]):
                pass

    def test_search_snapshot_closes_later_cross_reader_revocation(self):
        first = self.review(self.save())
        with services.search_projection(**self.common) as result:
            self.assertEqual(result["rows"][0]["pin"]["transcript_id"], first["id"])
            self.assertEqual(result["rows"][0]["pin"]["part_sha256"], self.part.sha256)
            pin = result["snapshot"]
        assert_snapshot(pin)
        self.authority.denied.add("READ_TRANSCRIPT")
        with self.assertRaises(cases.CaseConflict):
            assert_snapshot(pin)

    def test_preexisting_recording_read_denial_omits_only_optional_search_rows(self):
        self.review(self.save())
        self.authority.denied.add("READ_TRANSCRIPT")
        with services.search_projection(**self.common) as result:
            self.assertEqual(result["rows"], [])
            pin = result["snapshot"]
        assert_snapshot(pin)

    def test_late_identity_media_policy_and_row_withdrawal_reject_entire_projection(self):
        row = self.review(self.save())
        with self.assertRaises(cases.CaseConflict):
            with services.transcript_projection(**self.common, transcript_id=row["id"]):
                self.directory.identities["other"] = replace(
                    self.directory.identities["other"], active=False
                )
        self.directory.identities["other"] = replace(
            self.directory.identities["other"], active=True
        )
        with self.assertRaises(cases.CaseConflict):
            with services.search_projection(**self.common):
                self.review(row, action="WITHDRAW", subject_id="publisher")
        self.assertFalse(TranscriptAction.objects.filter(action="WITHDRAW").exists())
        with self.assertRaises(cases.CaseConflict):
            with services.search_projection(**self.common):
                self.rights.until = timezone.now() - timedelta(seconds=1)

    def test_stale_facts_hide_audio_and_text_instead_of_optional_fallback(self):
        released = self.release(self.review(self.save()))
        cases.add_followup(
            token=self.receipt["token"],
            text="new material facts",
            expected_revision=3,
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(preview.PreviewUnavailable):
            with public.publication_projection(self.publication.pk, include_media=False):
                pass
        with self.assertRaises(preview.PreviewUnavailable):
            with public.recording_projection(released["id"]):
                pass

    def test_actual_concurrent_edits_share_one_version_slot(self):
        ready = Barrier(2)

        def edit():
            close_old_connections()
            try:
                ready.wait(timeout=10)
                try:
                    return self.save()["number"]
                except cases.CaseConflict:
                    return "stale"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: edit(), range(2)))
        self.assertCountEqual(results, [1, "stale"])
        self.assertEqual(RecordingTranscript.objects.count(), 1)

    def test_sql_rejects_resealed_null_segment_and_cross_source(self):
        first = self.save()
        original = RecordingTranscript.objects.get(pk=first["id"])
        for changes in (
            {
                "segments": [
                    {
                        "char_start": None,
                        "char_end": 2,
                        "start_ms": 0,
                        "end_ms": 1,
                        "sha256": "0" * 64,
                    }
                ]
            },
            {"source_pins": {**original.source_pins, "part_sha256": "f" * 64}},
            {"change_kind": "UNKNOWN"},
            {"previous_id": None},
        ):
            values = {
                field.attname: getattr(original, field.attname)
                for field in original._meta.concrete_fields
                if field.attname not in {"canonical_payload", "digest", "created_at"}
            }
            values.update(
                id=uuid.uuid4(), request_key=uuid.uuid4(), number=2, previous_id=original.pk
            )
            values.update(changes)
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    services._seal(RecordingTranscript(**values))
        self.assertEqual(RecordingTranscript.objects.count(), 1)

    def test_sql_rejects_resealed_self_review_and_release(self):
        row = RecordingTranscript.objects.get(pk=self.save()["id"])
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                services._seal(
                    TranscriptAction(
                        transcript=row,
                        sequence=1,
                        previous_digest=row.digest,
                        action="REVIEW",
                        note="invalid self review",
                        subject_id=row.subject_id,
                        provider_id=row.provider_id,
                        auth_epoch=row.auth_epoch,
                        case_revision=3,
                        evidence_version=1,
                        request_key=uuid.uuid4(),
                        request_sha256="a" * 64,
                    )
                )
        media = PublicMediaEdition.objects.get(pk=self.prepare()["id"])
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                services._seal(
                    PublicMediaAction(
                        edition=media,
                        sequence=1,
                        previous_digest=media.digest,
                        action="RELEASE",
                        note="unreviewed direct release",
                        valid_until=timezone.now() + timedelta(minutes=5),
                        subject_id="publisher",
                        provider_id=row.provider_id,
                        auth_epoch=row.auth_epoch,
                        case_revision=3,
                        evidence_version=1,
                        request_key=uuid.uuid4(),
                        request_sha256="b" * 64,
                    )
                )

    def test_permission_callback_withdraws_before_projection_end_not_after_snapshot(self):
        first = self.review(self.save())

        def withdraw(values):
            if values["action"] == "READ_TRANSCRIPT":
                self.authority.hook = None
                self.review(first, action="WITHDRAW", subject_id="publisher")

        self.authority.hook = withdraw
        with self.assertRaises(cases.CaseConflict):
            with services.search_projection(**self.common):
                pass
        self.assertFalse(TranscriptAction.objects.filter(action="WITHDRAW").exists())

    def test_latest_media_lease_and_underlying_deadline_expire_during_read(self):
        released = self.release()
        with self.assertRaises(preview.PreviewUnavailable):
            with public.recording_projection(released["id"]):
                self.rights.until = timezone.now() - timedelta(seconds=1)

    def test_submitted_record_rolls_back_if_final_current_policy_revokes(self):
        def revoke(values):
            if values["action"] == "EDIT_TRANSCRIPT" and RecordingTranscript.objects.exists():
                self.authority.denied.add("EDIT_TRANSCRIPT")

        self.authority.hook = revoke
        with self.assertRaises(cases.CaseConflict):
            self.save()
        self.assertFalse(RecordingTranscript.objects.exists())
