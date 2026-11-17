"""Focused real PostgreSQL multipart, isolation, immutable and native form contracts."""

import io
import wave
from dataclasses import replace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from tests.casework.test_http import WEB_SETTINGS, Directory, hidden, post

from . import services
from .models import AnswerManifest, AnswerPart, PrivateAnswerRelease


def audio_fixture():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\x00\x00" * 800)
    return {"raw": output.getvalue(), "filename": "answer.wav", "media_type": "audio/wav"}


@override_settings(FATWA_ANSWER_MEDIA_ENABLED=True, FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True)
class AnswerMediaTests(TransactionTestCase):
    def setUp(self):
        self.receipt = cases.intake_case(
            original_question="سؤال اصطناعي محفوظ",
            source_event_id="answer-media-one",
            requester_id="requester-one",
            idempotency_key="answer-media-one",
            synthetic_fixtures_only=True,
        )
        self.directory = Directory()
        self.directory.grant(self.receipt["public_ref"])
        self.common = {
            "case_id": self.receipt["case_id"],
            "provider": self.directory,
            "subject_id": self.directory.current.subject_id,
            "synthetic_fixtures_only": True,
        }
        configured = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        configured.enable()
        self.addCleanup(configured.disable)

    def save(self, **changes):
        current = cases.read_case(**self.common)
        args = {
            **self.common,
            "expected_revision": current["revision"],
            "expected_evidence_version": current["evidence_version"],
            "text": "جواب بشري اصطناعي",
            "files": [audio_fixture()],
        }
        return services.save_multipart_answer(**{**args, **changes})

    def approve(self):
        current = cases.read_case(**self.common)
        return cases.record_decision(
            **self.common,
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            action="APPROVE",
            answer_id=current["answers"][-1]["id"],
        )

    def release(self, **changes):
        current = cases.read_case(**self.common)
        manifest = AnswerManifest.objects.get(answer_id=current["approved_answer_id"])
        args = {
            **self.common,
            "expected_revision": current["revision"],
            "expected_evidence_version": current["evidence_version"],
            "manifest_sha256": manifest.sha256,
            "confirmed": True,
        }
        return services.release_private(**{**args, **changes})

    def private(self):
        return services.requester_snapshot(
            token=self.receipt["token"], synthetic_fixtures_only=True
        )

    def test_text_audio_file_revision_approval_and_separate_private_release(self):
        self.save(
            files=[
                audio_fixture(),
                {"raw": b"human file answer", "filename": "answer.txt", "media_type": "text/plain"},
            ]
        )
        package = services.staff_snapshot(**self.common)["latest_package"]
        self.assertEqual([p["kind"] for p in package["parts"]], ["TEXT", "AUDIO", "FILE"])
        with self.assertRaises(cases.CaseConflict):
            self.private()
        approved = self.approve()
        with self.assertRaises(cases.CaseConflict):
            self.private()
        result = self.release()
        self.assertTrue(result["available"])
        self.assertFalse(result["delivery_verified"])
        self.assertFalse(result["read_confirmed"])
        private = self.private()
        self.assertEqual(private["package"]["answer_id"], approved["approved_answer_id"])
        part = private["package"]["parts"][1]
        self.assertEqual(
            services.requester_read(
                token=self.receipt["token"], part_id=part["id"], synthetic_fixtures_only=True
            )["raw"],
            audio_fixture()["raw"],
        )
        self.assertEqual(Case.objects.get().evidence_version, 1)

    def test_new_answer_and_new_facts_close_previous_media_and_release(self):
        self.save()
        self.approve()
        self.release()
        previous = self.private()["package"]["parts"][1]
        self.save(
            retained_part_ids=[previous["id"]],
            files=[{"raw": b"new answer file", "filename": "new.txt", "media_type": "text/plain"}],
        )
        self.assertEqual(AnswerManifest.objects.count(), 2)
        self.assertEqual(AnswerPart.objects.count(), 5)
        with self.assertRaises(cases.CaseConflict):
            services.requester_read(
                token=self.receipt["token"], part_id=previous["id"], synthetic_fixtures_only=True
            )
        self.approve()
        self.release()
        current = cases.read_case(**self.common)
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع جديدة",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.private()
        self.assertEqual(PrivateAnswerRelease.objects.count(), 2)

    def test_foreign_capability_foreign_retained_part_role_and_revocation_rejected(self):
        self.save()
        self.approve()
        self.release()
        part = self.private()["package"]["parts"][1]
        foreign = cases.intake_case(
            original_question="قضية أخرى",
            source_event_id="foreign",
            requester_id="foreign",
            idempotency_key="foreign",
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            services.requester_read(
                token=foreign["token"], part_id=part["id"], synthetic_fixtures_only=True
            )
        self.directory.current = replace(self.directory.current, role="ORGANIZER")
        with self.assertRaises(cases.CaseConflict):
            self.save()
        self.directory.current = replace(self.directory.current, role="MUFTI")
        self.directory.grant(foreign["public_ref"])
        with self.assertRaises(cases.CaseConflict):
            services.save_multipart_answer(
                **{**self.common, "case_id": foreign["case_id"]},
                expected_revision=1,
                expected_evidence_version=1,
                text="جواب آخر",
                files=[],
                retained_part_ids=[part["id"]],
            )
        self.directory.grant(self.receipt["public_ref"])
        cases.revoke_access(**self.common, requester_id="requester-one")
        with self.assertRaises(cases.CaseConflict):
            self.private()

    def test_default_closed_explicit_confirm_and_exact_approver_required(self):
        with override_settings(FATWA_ANSWER_MEDIA_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.save()
        self.save()
        self.approve()
        with self.assertRaises(cases.CaseConflict):
            self.release(confirmed=False)
        with override_settings(FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.release()
        self.directory.current = replace(self.directory.current, auth_epoch="different-epoch")
        with self.assertRaises(cases.CaseConflict):
            self.release()
        self.assertEqual(PrivateAnswerRelease.objects.count(), 0)

    def test_immutable_rows_no_late_parts_and_atomic_failure(self):
        self.save()
        part = AnswerPart.objects.order_by("ordinal").last()
        for operation in (
            lambda: AnswerPart.objects.filter(pk=part.pk).update(original=b"replacement"),
            lambda: AnswerManifest.objects.update(sha256="f" * 64),
            lambda: AnswerPart.objects.create(
                manifest=part.manifest,
                ordinal=3,
                kind=part.kind,
                original=part.original,
                sha256=part.sha256,
                size=part.size,
                media_type=part.media_type,
                filename=part.filename,
            ),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        with patch.object(
            AnswerPart.objects, "create", side_effect=RuntimeError("simulated store failure")
        ):
            with self.assertRaises(RuntimeError):
                self.save()
        self.assertEqual(Case.objects.get().answer_revision, 1)
        self.assertEqual(AnswerManifest.objects.count(), 1)
        self.approve()
        self.release()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrivateAnswerRelease.objects.update(manifest_sha256="0" * 64)

    def test_releasing_mufti_authority_withdrawal_closes_existing_private_release(self):
        self.save()
        self.approve()
        self.release()
        part = self.private()["package"]["parts"][1]
        original = self.directory.current
        for changed in (
            replace(original, role="ORGANIZER"),
            replace(original, case_keys=frozenset()),
            replace(original, auth_epoch="revoked-epoch"),
            replace(original, active=False),
        ):
            self.directory.current = changed
            with self.assertRaises(cases.CaseConflict):
                self.private()
            with self.assertRaises(cases.CaseConflict):
                services.requester_read(
                    token=self.receipt["token"], part_id=part["id"], synthetic_fixtures_only=True
                )
        self.directory.current = original
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            with self.assertRaises(cases.CaseConflict):
                self.private()

    def test_cross_editor_copy_preserves_files_but_not_approval_or_private_release(self):
        self.save()
        self.approve()
        self.release()
        old_part = self.private()["package"]["parts"][1]
        with cases._staff_case(
            self.common["case_id"], self.common["subject_id"], self.directory, True
        ) as (case, actor):
            previous = case.answers.latest("revision")
            case.answer_revision += 1
            answer = AnswerRevision.objects.create(
                case=case,
                revision=case.answer_revision,
                evidence_version=case.evidence_version,
                text="تحرير جديد مع إحالة",
                text_sha256=cases._digest("تحرير جديد مع إحالة"),
                subject_id=actor.subject_id,
                provider_id=self.directory.provider_id,
                auth_epoch=actor.auth_epoch,
            )
            case.stage, case.approved_answer = "UNDER_REVIEW", None
            cases._event(case, "SAVE_ANSWER", actor.subject_id, answer=answer)
            copied = services.clone_parts_for_new_answer(previous, answer)
        self.assertEqual(copied["parts"][1]["sha256"], old_part["sha256"])
        self.assertNotEqual(copied["parts"][1]["id"], old_part["id"])
        with self.assertRaises(cases.CaseConflict):
            services.requester_read(
                token=self.receipt["token"], part_id=old_part["id"], synthetic_fixtures_only=True
            )
        self.assertEqual(PrivateAnswerRelease.objects.count(), 1)

    def test_populated_guard_migration_reverse_reapply_preserves_originals(self):
        self.save()
        original = list(AnswerPart.objects.values_list("sha256", "original"))
        call_command("migrate", "answer_media", "0001", verbosity=0)
        call_command("migrate", "answer_media", "0002", verbosity=0)
        self.assertEqual(list(AnswerPart.objects.values_list("sha256", "original")), original)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnswerPart.objects.update(source="REPLACEMENT")

    def test_rejected_media_pending_clarification_and_stale_revision_do_not_write(self):
        with self.assertRaises(cases.CaseConflict):
            self.save(
                files=[
                    {"raw": b"not a pdf", "filename": "bad.pdf", "media_type": "application/pdf"}
                ]
            )
        self.assertEqual(AnswerManifest.objects.count(), 0)
        self.save()
        with self.assertRaises(cases.CaseConflict):
            self.save(expected_revision=1)
        current = cases.read_case(**self.common)
        cases.request_clarification(
            **self.common,
            text="وضح",
            expected_revision=current["revision"],
            expected_evidence_version=1,
        )
        with self.assertRaises(cases.CaseConflict):
            self.save()
        self.assertEqual(AnswerManifest.objects.count(), 1)

    @override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "apps.answer_media.urls"})
    def test_file_http_checks_current_staff_scope_and_requester_revocation(self):
        self.save()
        self.approve()
        self.release()
        part = self.private()["package"]["parts"][1]
        staff_path = f"/casework/staff/answer-media/{part['id']}/"
        requester_path = f"/casework/status/answer-media/{part['id']}/"
        staff = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1")
        requester = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1")
        login = staff.get("/casework/staff/login/")
        self.assertEqual(
            post(
                staff, "/casework/staff/login/", {"credential": self.directory.credential}, login
            ).status_code,
            303,
        )
        unlock = requester.get("/casework/status/")
        self.assertEqual(
            post(
                requester,
                "/casework/status/",
                {"action": "unlock", "token": self.receipt["token"]},
                unlock,
            ).status_code,
            303,
        )
        # The integration owner installs the general UUID route policy. Isolated
        # lane test admits only these exact fixture paths into the existing guard.
        with patch.dict(
            "apps.casework_web.guard.ROUTES",
            {
                staff_path: ("GET", "HEAD"),
                requester_path: ("GET", "HEAD"),
            },
        ):
            self.assertEqual(staff.get(staff_path).content, audio_fixture()["raw"])
            self.assertEqual(requester.get(requester_path).content, audio_fixture()["raw"])
            original = self.directory.current
            for changed in (
                replace(original, role="ORGANIZER"),
                replace(original, case_keys=frozenset()),
            ):
                self.directory.current = changed
                self.assertEqual(staff.get(staff_path).status_code, 404)
                self.assertEqual(requester.get(requester_path).status_code, 404)
            self.directory.current = original
            cases.revoke_access(**self.common, requester_id="requester-one")
            self.assertEqual(requester.get(requester_path).status_code, 404)

    @override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "apps.answer_media.urls"})
    def test_native_multipart_save_preview_and_csrf(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory):
            page = client.get("/casework/staff/login/")
            self.assertEqual(
                post(
                    client,
                    "/casework/staff/login/",
                    {"credential": self.directory.credential},
                    page,
                ).status_code,
                303,
            )
            page = client.get("/casework/staff/")
            page = post(
                client,
                "/casework/staff/",
                {"action": "answer_media", "case_ref": self.receipt["public_ref"]},
                page,
            )
            self.assertEqual(page.status_code, 200)
            data = {
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                "action": "answer_media_save",
                "case_ref": self.receipt["public_ref"],
                "revision": "1",
                "evidence_version": "1",
                "text": "جواب بشري مع صوت",
                "retain": "no",
                "synthetic_only": "yes",
                "answer_file": SimpleUploadedFile(
                    "answer.wav", audio_fixture()["raw"], content_type="audio/wav"
                ),
            }
            response = client.post("/casework/staff/", data)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertContains(response, "<audio")
            self.assertContains(response, "غير معتمد حاليًا")
            self.assertEqual(AnswerPart.objects.count(), 2)
            self.assertEqual(
                client.post(
                    "/casework/staff/",
                    {"action": "answer_media", "case_ref": self.receipt["public_ref"]},
                ).status_code,
                403,
            )
