"""V8 cross-editor and media-delivery boundaries on one canonical synthetic case."""

from dataclasses import replace
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.answer_media import services as answers
from apps.answer_media.models import AnswerManifest, AnswerPart, PrivateAnswerRelease
from apps.case_attachments import services as attachments
from apps.case_citations import services as citations
from apps.case_citations.models import AnswerCitation
from apps.casework import delivery
from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.private_media.fixtures import synthetic_files
from apps.reference.ingest import ingest_catalog
from apps.requester_access_review.services import requester_snapshot
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import WEB_SETTINGS, post
from tests.reference.test_catalog import fixture


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_CASE_ATTACHMENTS_ENABLED": True,
        "FATWA_CASE_CITATIONS_ENABLED": True,
        "FATWA_ANSWER_MEDIA_ENABLED": True,
        "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    }
)
class V8IntegrationTests(CaseDeliveryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        configured = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        configured.enable()
        self.addCleanup(configured.disable)
        self.files = {
            mime: {"filename": name, "media_type": mime, "raw": raw}
            for name, mime, raw in synthetic_files()
        }
        spec, rows = fixture()
        spec = replace(spec, source_book_id="622")
        preview = ingest_catalog(spec, rows)
        self.edition_id = ingest_catalog(
            spec, rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id

    def cited(self, text="جواب بشري متعدد الإحالات"):
        current = cases.read_case(**self.staff())
        selections = []
        for row_id in (2, 5):
            source = citations.read_source(
                **self.staff(), edition_id=self.edition_id, source_row_id=row_id
            )
            selections.append(
                {
                    "edition_id": self.edition_id,
                    "source_row_id": row_id,
                    "source_sha256": source["source_sha256"],
                    "editorial_note": "تحرير بشري",
                }
            )
        return citations.save_cited_answer(
            **self.staff(),
            text=text,
            selections=selections,
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )

    def compound(self):
        current = cases.read_case(**self.staff())
        return answers.save_multipart_answer(
            **self.staff(),
            text=current["answers"][-1]["text"],
            files=[self.files["application/pdf"], self.files["audio/wav"]],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )

    def approve_release(self):
        current = cases.read_case(**self.staff())
        current = cases.record_decision(
            **self.staff(),
            action="APPROVE",
            answer_id=current["answers"][-1]["id"],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        manifest = AnswerManifest.objects.get(answer_id=current["approved_answer_id"])
        answers.release_private(
            **self.staff(),
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )
        return manifest

    def private(self):
        return answers.requester_snapshot(token=self.a["token"], synthetic_fixtures_only=True)

    def test_two_editors_preserve_same_revision_references_and_files_without_inheriting_release(
        self,
    ):
        self.cited()
        original_citations = set(AnswerCitation.objects.values_list("pk", flat=True))
        self.compound()
        manifest = self.approve_release()
        self.assertEqual(AnswerCitation.objects.filter(answer=manifest.answer).count(), 2)
        self.assertTrue(
            original_citations.isdisjoint(
                AnswerCitation.objects.filter(answer=manifest.answer).values_list("pk", flat=True)
            )
        )
        first_parts = list(manifest.parts.order_by("ordinal"))
        self.assertEqual(len(first_parts), 3)
        current = self.private()
        self.assertEqual(current["package"]["answer_id"], str(manifest.answer_id))
        self.assertFalse(current["delivery_verified"])
        self.assertFalse(current["read_confirmed"])
        with self.assertRaisesRegex(cases.CaseConflict, "unsupported_media"):
            delivery.prepare_case_delivery(**self.staff())
        # The original signed-text policy is unchanged: this portal release is
        # never passed off as verified provider delivery of text or media.
        signed = requester_snapshot(
            self.a["token"],
            verifier=self.channel_verifier,
            show_approved_answer=True,
            synthetic_fixtures_only=True,
        )
        self.assertIsNone(signed["private_answer"])
        self.assertEqual(
            signed["case"]["delivery_status"], "UNSUPPORTED_MEDIA_REQUIRES_HUMAN_ACTION"
        )
        revised = self.cited("نص منقح مع نفس الملفات وإحالتين جديدتين")
        self.assertIsNone(revised["approved_answer_id"])
        copied = AnswerManifest.objects.get(answer__revision=3)
        copied_parts = list(copied.parts.order_by("ordinal"))
        self.assertEqual(
            [bytes(p.original) for p in copied_parts[1:]],
            [bytes(p.original) for p in first_parts[1:]],
        )
        self.assertEqual(copied_parts[0].original, copied.answer.text.encode())
        self.assertFalse(PrivateAnswerRelease.objects.filter(manifest=copied).exists())
        with self.assertRaises(cases.CaseConflict):
            self.private()
        for part in first_parts[1:]:
            with self.assertRaises(cases.CaseConflict):
                answers.requester_read(
                    token=self.a["token"], part_id=part.pk, synthetic_fixtures_only=True
                )

    def test_release_authority_revocation_and_new_evidence_close_availability(self):
        self.cited()
        self.compound()
        manifest = self.approve_release()
        self.assertTrue(self.private()["package"]["released"])
        self.directory.epoch = "revoked-epoch"
        with self.assertRaises(cases.CaseConflict):
            self.private()
        self.directory.epoch = "epoch-1"
        self.directory.refs = frozenset()
        with self.assertRaises(cases.CaseConflict):
            self.private()
        self.directory.refs = frozenset({self.a["public_ref"]})
        current = cases.read_case(**self.staff())
        attachment = attachments.upload(
            token=self.a["token"],
            **self.files["image/png"],
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.private()
        self.assertEqual(
            attachments.requester_read(
                token=self.a["token"], attachment_id=attachment["id"], synthetic_fixtures_only=True
            )["raw"],
            self.files["image/png"]["raw"],
        )
        # Evidence originals and answer originals are separate resources.
        with self.assertRaises(cases.CaseConflict):
            answers.requester_read(
                token=self.a["token"], part_id=attachment["id"], synthetic_fixtures_only=True
            )
        self.assertEqual(AnswerRevision.objects.count(), 2)
        self.assertEqual(AnswerPart.objects.filter(manifest=manifest).count(), 3)

    def test_guarded_inline_head_and_denials_use_capability_not_url(self):
        self.cited()
        self.compound()
        manifest = self.approve_release()
        part = manifest.parts.get(ordinal=2)
        url = f"/casework/status/answer-media/{part.pk}/"
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.assertEqual(client.get(url).status_code, 404)

        page = client.get("/casework/status/")
        self.assertEqual(
            post(
                client, "/casework/status/", {"action": "unlock", "token": self.a["token"]}, page
            ).status_code,
            303,
        )
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, bytes(part.original))
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(client.head(url).content, b"")
        self.assertEqual(client.get(url + "?token=anything").status_code, 400)
        self.assertEqual(client.post(url).status_code, 405)
        cases.revoke_access(**self.staff(), requester_id="requester-a")
        self.assertEqual(client.get(url).status_code, 404)

    def test_legacy_casework_profile_keeps_durable_media_and_unknown_profile_denies(self):
        from config.settings import casework_review, casework_test

        self.assertIn("apps.answer_media", casework_test.INSTALLED_APPS)
        self.assertIn("apps.answer_media", casework_review.INSTALLED_APPS)
        self.cited()
        self.compound()
        self.approve_release()
        with override_settings(
            FATWA_ANSWER_MEDIA_ENABLED=False, FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=False
        ):
            with self.assertRaisesRegex(cases.CaseConflict, "unsupported_media"):
                delivery.prepare_case_delivery(**self.staff())
        with patch("apps.casework.services.django_apps.is_installed", return_value=False):
            with self.assertRaisesRegex(cases.CaseConflict, "answer_media_schema_unavailable"):
                delivery.prepare_case_delivery(**self.staff())

    def test_canonical_approval_runs_content_validation_before_any_decision(self):
        self.cited()
        self.compound()
        current = cases.read_case(**self.staff())
        with patch(
            "apps.answer_media.services.validate_for_approval",
            side_effect=cases.CaseConflict("answer_media_content_invalid"),
        ):
            with self.assertRaisesRegex(cases.CaseConflict, "answer_media_content_invalid"):
                cases.record_decision(
                    **self.staff(),
                    action="APPROVE",
                    answer_id=current["answers"][-1]["id"],
                    expected_revision=current["revision"],
                    expected_evidence_version=current["evidence_version"],
                )
        after = cases.read_case(**self.staff())
        self.assertEqual(after["revision"], current["revision"])
        self.assertIsNone(after["approved_answer_id"])
        self.assertFalse(PrivateAnswerRelease.objects.exists())
        self.approve_release()

    def test_revocation_during_parsing_denies_approval_and_release_atomically(self):
        self.cited()
        self.compound()
        current = cases.read_case(**self.staff())
        parser = answers.validate_for_approval

        def revoke_after_parse(answer):
            result = parser(answer)
            self.directory.epoch = "revoked-during-parse"
            return result

        with patch(
            "apps.answer_media.services.validate_for_approval", side_effect=revoke_after_parse
        ):
            with self.assertRaisesRegex(cases.CaseConflict, "case_identity_changed"):
                cases.record_decision(
                    **self.staff(),
                    action="APPROVE",
                    answer_id=current["answers"][-1]["id"],
                    expected_revision=current["revision"],
                    expected_evidence_version=current["evidence_version"],
                )
        self.directory.epoch = "epoch-1"
        after = cases.read_case(**self.staff())
        self.assertEqual(after["revision"], current["revision"])
        self.assertIsNone(after["approved_answer_id"])
        approved = cases.record_decision(
            **self.staff(),
            action="APPROVE",
            answer_id=current["answers"][-1]["id"],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        manifest = AnswerManifest.objects.get(answer_id=approved["approved_answer_id"])
        with patch(
            "apps.answer_media.services.validate_for_approval", side_effect=revoke_after_parse
        ):
            with self.assertRaisesRegex(cases.CaseConflict, "case_identity_changed"):
                answers.release_private(
                    **self.staff(),
                    confirmed=True,
                    manifest_sha256=manifest.sha256,
                    expected_revision=approved["revision"],
                    expected_evidence_version=approved["evidence_version"],
                )
        self.assertFalse(PrivateAnswerRelease.objects.exists())
