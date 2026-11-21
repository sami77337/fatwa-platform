"""Real canonical reads/writes, byte validation, independent rights and revocation."""

import uuid
from dataclasses import replace

from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvent, CaseEvidence, CaseSource
from apps.library_preview import services as preview
from tests.casework.test_http import post

from . import public, services
from .models import LibraryBlob, LibraryDecision, LibraryItem, LibraryVersion
from .test_support import FEATURES, LibraryFixture, payload, video


@override_settings(**FEATURES)
class LibraryTests(LibraryFixture, TransactionTestCase):
    def originals(self):
        return [
            list(model.objects.values())
            for model in (CaseSource, CaseEvidence, CaseEvent, AnswerRevision)
        ]

    def test_real_file_read_versions_rights_and_canonical_originals(self):
        original = self.originals()
        raw = "نص اصطناعي\r\n  محفوظ كما هو  \n".encode()
        first = self.write(file_bytes=raw, filename="original.txt", media_type="text/plain")
        with self.assertRaises(cases.CaseConflict):
            services.file_content(**self.common, version_id=first["version_id"])
        approved = self.approve(first)
        self.assertEqual(
            services.file_content(**self.common, version_id=first["version_id"])["raw"], raw
        )
        second = self.write(
            namespace=first["namespace"],
            external_id=first["external_id"],
            expected_version=1,
            payload=payload(edition_label="طبعة ثانية موصوفة"),
        )
        self.assertEqual(second["file"]["sha256"], first["file"]["sha256"])
        self.assertEqual(LibraryBlob.objects.count(), 1)
        with self.assertRaises(cases.CaseConflict):
            services.file_content(**self.common, version_id=second["version_id"])
        self.assertEqual(
            services.read_material(**self.common, version_id=approved["version_id"])["payload"][
                "edition_label"
            ],
            payload()["edition_label"],
        )
        self.assertEqual(self.originals(), original)

    def test_descriptive_references_have_no_false_reader_and_never_inherit_rights(self):
        row = self.write()
        released = self.release(row, uses=["PUBLIC_METADATA", "EXPORT", "OFFLINE", "CITE"])
        with public.public_projection() as snapshot:
            record = snapshot.read(row["version_id"])
            self.assertIsNone(record["file"])
            self.assertEqual(record["recorded_text"], "")
            with self.assertRaises(preview.PreviewUnavailable):
                snapshot.content(row["version_id"])
        revised = self.write(
            namespace=row["namespace"],
            external_id=row["external_id"],
            expected_version=1,
            payload=payload(title="تعديل بشري غير منشور"),
        )
        with public.public_projection() as snapshot:
            self.assertIn(released["version_id"], snapshot.records)
            self.assertNotIn(revised["version_id"], snapshot.records)

    def test_actual_video_is_decoded_and_exact_bytes_are_returned(self):
        raw = video()
        row = self.write(
            payload=payload("VIDEO"),
            file_bytes=raw,
            filename="synthetic.webm",
            media_type="video/webm",
        )
        self.assertGreater(row["file"]["duration_seconds"], 0)
        row = self.release(row)
        with public.public_projection() as snapshot:
            self.assertEqual(snapshot.content(row["version_id"])["raw"], raw)
        for bad in (b"<script>not video</script>", raw[:40]):
            with self.assertRaises(cases.CaseConflict):
                self.write(
                    payload=payload("VIDEO"),
                    file_bytes=bad,
                    filename="bad.webm",
                    media_type="video/webm",
                )
        self.assertEqual(LibraryItem.objects.count(), 1)

    def test_actual_audio_requires_current_rights_and_native_reader_returns_exact_bytes(self):
        from apps.answer_media.tests import audio_fixture

        audio = audio_fixture()
        row = self.write(
            payload=payload("AUDIO"),
            file_bytes=audio["raw"],
            filename="library-audio.wav",
            media_type=audio["media_type"],
        )
        self.assertGreater(row["file"]["duration_seconds"], 0)
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        login = client.get("/casework/staff/login/")
        self.assertEqual(
            post(
                client,
                "/casework/staff/login/",
                {"credential": "synthetic-editor-credential-32-characters"},
                login,
            ).status_code,
            303,
        )
        url = f"/casework/staff/library/{row['version_id']}/file/"
        self.assertEqual(client.get(url).status_code, 404)
        self.approve(row)
        page = client.get("/casework/staff/")
        opened = post(
            client,
            "/casework/staff/",
            {
                "action": "rl_item",
                "case_ref": self.receipt["public_ref"],
                "version_id": row["version_id"],
            },
            page,
        )
        self.assertContains(opened, '<audio class="library-player" controls')
        content = client.get(url)
        self.assertEqual(content.status_code, 200)
        self.assertEqual(content.content, audio["raw"])
        self.assertEqual(content["Content-Type"], audio["media_type"])
        self.assertEqual(content["X-Content-SHA256"], row["file"]["sha256"])
        self.authority.denied.add(("READ", row["digest"]))
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(LibraryVersion.objects.count(), 1)

    def test_separate_case_ownership_does_not_merge_logical_materials(self):
        raw = b"synthetic shared content"
        a = self.write(file_bytes=raw, filename="a.txt", media_type="text/plain")
        b = self.write(file_bytes=raw, filename="b.txt", media_type="text/plain")
        self.assertNotEqual(a["item_id"], b["item_id"])
        self.assertEqual(a["file"]["sha256"], b["file"]["sha256"])
        self.approve(a)
        with self.assertRaises(cases.CaseConflict):
            services.file_content(**self.common, version_id=b["version_id"])

    def test_replay_stale_version_unknown_fields_and_source_identity(self):
        key = uuid.uuid4()
        row = self.write(request_key=key, external_id="same")
        replay = self.write(request_key=key, external_id="same")
        self.assertEqual(row["version_id"], replay["version_id"])
        for changes in (
            {"payload": payload(title="different"), "request_key": key, "external_id": "same"},
            {"external_id": "same", "expected_version": 0},
            {"payload": payload(approved=True)},
            {"namespace": "../unsafe"},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.write(**changes)
        self.assertEqual(LibraryVersion.objects.count(), 1)

    def test_self_review_and_shared_approver_are_rejected(self):
        row = self.write()
        with self.assertRaises(cases.CaseConflict):
            self.decide(row, "REVIEW", subject_id="editor")
        row = self.decide(row, "REVIEW")
        for subject in ("editor", "other"):
            with self.assertRaises(cases.CaseConflict):
                self.decide(row, "APPROVE", subject_id=subject, uses=["PUBLIC_METADATA"])
        self.assertEqual(LibraryDecision.objects.count(), 1)

    def test_native_sql_guards_protect_sources_versions_and_decisions(self):
        row = self.write(file_bytes=b"synthetic text", filename="test.txt", media_type="text/plain")
        self.approve(row)
        for model, field, value in (
            (LibraryBlob, "size", 1),
            (LibraryItem, "external_id", "changed"),
            (LibraryVersion, "payload", {}),
            (LibraryDecision, "note", "changed"),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.all().update(**{field: value})
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.all().delete()

    def test_database_rejects_null_kind_and_language_even_with_a_valid_seal(self):
        first = LibraryVersion.objects.get(pk=self.write()["version_id"])
        for field in ("kind", "language"):
            with self.subTest(field=field):
                candidate = LibraryVersion(
                    item=first.item,
                    previous=first,
                    number=2,
                    payload=payload(**{field: None}),
                    filename="",
                    request_key=uuid.uuid4(),
                    request_sha256="a" * 64,
                    subject_id="editor",
                    provider_id=self.directory.provider_id,
                    auth_epoch="epoch-1",
                    case_revision=1,
                    evidence_version=1,
                )
                with (
                    self.assertRaisesRegex(IntegrityError, "library edition identity invalid"),
                    transaction.atomic(),
                ):
                    services._seal(candidate)
        self.assertEqual(LibraryVersion.objects.count(), 1)

    def test_latest_item_read_rejects_and_rolls_back_late_new_edition(self):
        first = self.write(external_id="latest-read-race")
        appended = False

        def append_once(values):
            nonlocal appended
            if values["action"] == "VIEW" and not appended:
                appended = True
                self.write(
                    namespace=first["namespace"],
                    external_id=first["external_id"],
                    expected_version=1,
                    payload=payload(title="نسخة أحدث أضيفت أثناء فحص الصلاحية"),
                )

        self.authority.hook = append_once
        with self.assertRaisesRegex(cases.CaseConflict, "library_head_changed"):
            services.read_material(**self.common, item_id=first["item_id"])
        self.assertTrue(appended)
        self.assertEqual(LibraryVersion.objects.filter(item_id=first["item_id"]).count(), 1)

    def test_explicit_historical_read_remains_exact_when_a_newer_edition_is_added(self):
        first = self.write(external_id="exact-historical-read")
        appended = False

        def append_once(values):
            nonlocal appended
            if values["action"] == "VIEW" and not appended:
                appended = True
                self.write(
                    namespace=first["namespace"],
                    external_id=first["external_id"],
                    expected_version=1,
                    payload=payload(title="نسخة ثانية لا تبدل المرجع التاريخي"),
                )

        self.authority.hook = append_once
        historical = services.read_material(
            **self.common, item_id=first["item_id"], version_number=1
        )
        self.assertEqual(historical["version_id"], first["version_id"])
        self.assertEqual(historical["payload"], first["payload"])
        self.assertEqual(LibraryVersion.objects.filter(item_id=first["item_id"]).count(), 2)
        self.assertEqual(
            services.read_material(**self.common, version_id=first["version_id"])["digest"],
            first["digest"],
        )
        self.assertEqual(
            services.read_material(**self.common, item_id=first["item_id"])["number"], 2
        )

    def test_missing_action_and_final_identity_revocation_rollback_writes(self):
        self.authority.denied.add("EDIT")
        with self.assertRaises(cases.CaseConflict):
            self.write()
        self.authority.denied.clear()
        count = 0

        def revoke(values):
            nonlocal count
            if values["action"] == "EDIT":
                count += 1
                if count == 2:
                    self.directory.identities["editor"] = replace(
                        self.directory.identities["editor"], active=False
                    )

        self.authority.hook = revoke
        with self.assertRaises(cases.CaseConflict):
            self.write()
        self.assertFalse(LibraryItem.objects.exists())
        self.assertFalse(LibraryVersion.objects.exists())

    def test_late_public_withdrawal_discards_response_and_rolls_back_nested_action(self):
        row = self.release(
            self.write(
                file_bytes=b"public synthetic bytes", filename="public.txt", media_type="text/plain"
            )
        )
        with self.assertRaises(preview.PreviewUnavailable):
            with public.public_projection() as snapshot:
                self.assertEqual(
                    snapshot.content(row["version_id"])["raw"], b"public synthetic bytes"
                )
                self.decide(row, "WITHDRAW")
        self.assertFalse(LibraryDecision.objects.filter(action="WITHDRAW").exists())

    def test_scope_shrink_and_public_lease_revocation_deny_all_content(self):
        row = self.release(
            self.write(file_bytes=b"source", filename="source.txt", media_type="text/plain")
        )
        self.decide(row, "REVOKE")
        with public.public_projection() as snapshot:
            self.assertEqual(snapshot.records, {})
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset()
        )
        with self.assertRaises(cases.CaseConflict):
            services.read_material(**self.common, version_id=row["version_id"])
