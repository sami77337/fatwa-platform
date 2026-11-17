"""Current CITE rights protect the entire canonical answer and every export path."""

import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerManifest, AnswerPart, PrivateAnswerRelease
from apps.case_citations import services as citations
from apps.case_citations.tests import source_fixture
from apps.casework import delivery
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision
from apps.composite_delivery import desk
from apps.composite_delivery import services as composite
from apps.composite_delivery.simulator import OfflineProviderSimulator
from apps.delivery_planner.planner import Capabilities
from apps.reference.models import ReferenceHeading
from apps.requester_access_review import services as requester
from apps.source_rights import services as rights
from apps.source_rights.authority import SourceRightsAuthority
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_core import TestDirectory


class Directory(TestDirectory):
    def resolve(self, subject_id):
        if subject_id == "synthetic-rights-reviewer":
            return replace(super().resolve("synthetic-mufti"), subject_id=subject_id)
        return super().resolve(subject_id)


class Authority(SourceRightsAuthority):
    def __init__(self, case_ref):
        self.case_ref = case_ref

    def permits(self, **kwargs):
        return kwargs["case_ref"] == self.case_ref and kwargs["subject_id"] in {
            "synthetic-mufti",
            "synthetic-rights-reviewer",
        }


@override_settings(
    FATWA_SOURCE_RIGHTS_ENABLED=True,
    FATWA_SOURCE_RIGHTS_ENFORCED=True,
    FATWA_CASE_CITATIONS_ENABLED=True,
    FATWA_ANSWER_MEDIA_ENABLED=True,
    FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True,
    FATWA_COMPOSITE_DELIVERY_ENABLED=True,
)
class AnswerRightsTests(CaseDeliveryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.directory = Directory([self.a["public_ref"]])
        profile = composite.ChannelProfile(
            Capabilities(
                composite.SIMULATOR_PROVIDER,
                "synthetic.v1",
                frozenset({"text", "document"}),
                6000,
                True,
            ),
            192000,
            frozenset({"text/plain"}),
        )
        configured = override_settings(
            FATWA_SOURCE_RIGHTS_AUTHORITY=Authority(self.a["public_ref"]),
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=lambda _: profile,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.catalog = source_fixture()
        heading = ReferenceHeading.objects.get(edition_id=self.catalog, source_row_id=2)
        self.source = rights.register(**self.staff(), kind="TOC_METADATA", target_id=heading.pk)
        self.grant = self.allow()

    def allow(self, number=0):
        row = rights.propose(
            **self.staff(),
            source_id=self.source["id"],
            expected_number=number,
            uses=["READ", "CITE"],
            basis="Synthetic explicitly reviewed rights",
            note="Synthetic proposal",
            ttl_minutes=60,
        )
        self.review_right(row, "APPROVE")
        return row

    def review_right(self, row, action):
        return rights.review(
            **{**self.staff(), "subject_id": "synthetic-rights-reviewer"},
            revision_id=row["id"],
            action=action,
            confirmed=True,
            note="Synthetic review",
        )

    def cited(self, multipart=False):
        source = citations.read_source(**self.staff(), edition_id=self.catalog, source_row_id=2)
        draft = citations.save_cited_answer(
            **self.staff(),
            text="Exact synthetic human answer",
            selections=[
                dict(
                    edition_id=self.catalog,
                    source_row_id=2,
                    source_sha256=source["source_sha256"],
                    editorial_note="Human note",
                )
            ],
            expected_revision=1,
            expected_evidence_version=1,
        )
        if multipart:
            draft = media.save_multipart_answer(
                **self.staff(),
                text=draft["answers"][-1]["text"],
                files=[
                    dict(
                        raw=b"Exact synthetic original",
                        filename="answer.txt",
                        media_type="text/plain",
                    )
                ],
                expected_revision=draft["revision"],
                expected_evidence_version=1,
            )
        return draft

    def decide(self, draft, action="APPROVE"):
        return cases.record_decision(
            **self.staff(),
            answer_id=draft["answers"][-1]["id"],
            action=action,
            note="Human correction needed" if action == "RETURN_FOR_CHANGES" else "",
            expected_revision=draft["revision"],
            expected_evidence_version=1,
        )

    def release(self, current):
        manifest = AnswerManifest.objects.get(answer_id=current["approved_answer_id"])
        return media.release_private(
            **self.staff(),
            expected_revision=current["revision"],
            expected_evidence_version=1,
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )

    def test_revoked_cite_blocks_approval_but_human_return_remains_possible(self):
        draft = self.cited()
        self.review_right(self.grant, "REVOKE")
        with self.assertRaises(cases.CaseConflict):
            self.decide(draft)
        self.assertFalse(CaseDecision.objects.exists())
        self.assertEqual(Case.objects.get(pk=self.a["case_id"]).revision, draft["revision"])
        self.assertEqual(self.decide(draft, "RETURN_FOR_CHANGES")["status"], "RETURNED_FOR_CHANGES")

    def test_expiry_blocks_approval_and_new_reviewed_grant_restores_same_draft(self):
        draft = self.cited()
        with patch(
            "apps.source_rights.services.timezone.now",
            return_value=timezone.now() + timedelta(hours=2),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.decide(draft)
        self.assertFalse(CaseDecision.objects.exists())
        self.review_right(self.grant, "REVOKE")
        self.allow(number=1)
        self.assertEqual(self.decide(draft)["approved_answer_id"], draft["answers"][-1]["id"])

    def test_revocation_closes_release_snapshot_and_direct_media_without_changing_original(self):
        approved = self.decide(self.cited(multipart=True))
        self.release(approved)
        part = AnswerPart.objects.get(manifest__answer_id=approved["approved_answer_id"], ordinal=2)
        original = media.requester_read(
            token=self.a["token"], part_id=part.pk, synthetic_fixtures_only=True
        )
        before = (part.sha256, part.size, bytes(part.original), approved["approved_answer_id"])
        self.review_right(self.grant, "REVOKE")
        operations = [
            lambda: self.release(approved),
            lambda: media.requester_snapshot(token=self.a["token"], synthetic_fixtures_only=True),
            lambda: media.requester_read(
                token=self.a["token"], part_id=part.pk, synthetic_fixtures_only=True
            ),
            lambda: media.staff_read(
                part_id=part.pk,
                subject_id="synthetic-mufti",
                provider=self.directory,
                synthetic_fixtures_only=True,
            ),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(cases.CaseConflict):
                operation()
        with cases._token_case(self.a["token"], True) as case:
            self.assertFalse(media.private_availability_for_locked_case(case)["available"])
        part.refresh_from_db()
        self.assertEqual(
            before,
            (
                part.sha256,
                part.size,
                bytes(part.original),
                str(Case.objects.get(pk=self.a["case_id"]).approved_answer_id),
            ),
        )
        self.assertEqual(original["raw"], b"Exact synthetic original")
        self.assertEqual(PrivateAnswerRelease.objects.count(), 1)

    def test_revoked_text_answer_cannot_stage_export_or_claim_current_delivery(self):
        self.decide(self.cited())
        signed = self.receipt(self.request())
        self.stage(receipt=signed)
        lease = self.reserve()
        self.assertIsNotNone(lease)
        self.review_right(self.grant, "REVOKE")
        operations = [
            self.request,
            lambda: self.stage(receipt=signed),
            self.reserve,
            lambda: delivery.resolve_case_delivery_text(
                **self.staff(), lease=lease, verify_receipt=self.approval_verifier
            ),
            lambda: delivery.record_case_provider_event(
                **self.staff(), lease=lease, event=self.event(lease), verifier=self.channel_verifier
            ),
            lambda: requester.requester_snapshot(
                self.a["token"],
                verifier=self.channel_verifier,
                show_approved_answer=True,
                synthetic_fixtures_only=True,
            ),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(cases.CaseConflict):
                operation()
        self.assertEqual(AnswerRevision.objects.get().text, "Exact synthetic human answer")

    def test_expired_composite_rights_block_preparation_export_and_current_outcome(self):
        self.decide(self.cited(multipart=True))
        request = composite.prepare_composite_delivery(**self.staff())
        signed = self.receipt(request)
        composite.stage_composite_delivery(
            **self.staff(), receipt=signed, verify_receipt=self.approval_verifier
        )
        lease = composite.reserve_composite_part(
            **self.staff(),
            worker_id="synthetic-worker",
            verify_worker=lambda *_: True,
            verify_receipt=self.approval_verifier,
        )
        simulator = OfflineProviderSimulator(synthetic_fixtures_only=True)
        operations = [
            lambda: composite.prepare_composite_delivery(**self.staff()),
            lambda: composite.stage_composite_delivery(
                **self.staff(), receipt=signed, verify_receipt=self.approval_verifier
            ),
            lambda: composite.resolve_composite_part(
                **self.staff(), lease=lease, verify_receipt=self.approval_verifier
            ),
            lambda: composite.composite_status(**self.staff(), verifier=simulator.verifier),
        ]
        with patch(
            "apps.source_rights.services.timezone.now",
            return_value=timezone.now() + timedelta(hours=2),
        ):
            for operation in operations:
                with self.subTest(operation=operation), self.assertRaises(cases.CaseConflict):
                    operation()

    def test_uncited_answer_still_approves_and_releases_without_rights_authority(self):
        with override_settings(FATWA_SOURCE_RIGHTS_AUTHORITY=None):
            approved = self.approve()
            self.assertTrue(self.request())
            draft = media.save_multipart_answer(
                **self.staff(),
                text="Uncited human answer",
                files=[dict(raw=b"Uncited bytes", filename="answer.txt", media_type="text/plain")],
                expected_revision=approved["revision"],
                expected_evidence_version=1,
            )
            current = self.decide(draft)
            self.release(current)
            package = media.requester_snapshot(token=self.a["token"], synthetic_fixtures_only=True)
            self.assertEqual(package["package"]["text"], "Uncited human answer")

    def test_maintenance_admission_survives_commit_and_blocks_all_four_service_families(self):
        from apps.platform_recovery import maintenance
        from apps.platform_recovery.integration import MaintenanceUnavailable, require_admission
        from apps.private_media.filesystem import FileSystemStorage

        with tempfile.TemporaryDirectory(prefix="v11-answer-maintenance-") as folder:
            root = Path(folder)
            control = root / "maintenance"
            control.mkdir(mode=0o700)
            storage = FileSystemStorage(root / "originals", synthetic_fixtures_only=True)
            maintenance.initialize(root=control, storage=storage, synthetic_fixtures_only=True)
            seen = []
            event = cases._event

            def recorded(*args, **kwargs):
                result = event(*args, **kwargs)

                def committed():
                    require_admission()
                    seen.append("lease-through-commit")

                transaction.on_commit(committed)
                return result

            with override_settings(
                FATWA_RECOVERY_MAINTENANCE_REQUIRED=True, FATWA_RECOVERY_MAINTENANCE_ROOT=control
            ):
                with patch.object(cases, "_event", side_effect=recorded):
                    cases.save_answer(
                        **self.staff(),
                        text="Synthetic maintenance boundary",
                        expected_revision=1,
                        expected_evidence_version=1,
                    )
                self.assertEqual(seen, ["lease-through-commit"])
                self.assertEqual(
                    desk.read_delivery_desk(**self.staff())["public_ref"], self.a["public_ref"]
                )
                with self.assertRaises(MaintenanceUnavailable):
                    require_admission()
                maintenance.enter(root=control, synthetic_fixtures_only=True)
                operations = [
                    lambda: cases.read_case(**self.staff()),
                    self.request,
                    lambda: media.staff_snapshot(**self.staff()),
                    lambda: composite.prepare_composite_delivery(**self.staff()),
                    lambda: desk.read_delivery_desk(**self.staff()),
                    lambda: desk.apply_desk_action(
                        **self.staff(),
                        action="composite_reconcile",
                        revision=2,
                        evidence_version=1,
                        plan_sha256="0" * 64,
                    ),
                ]
                for operation in operations:
                    with (
                        self.subTest(operation=operation),
                        self.assertRaises(MaintenanceUnavailable),
                    ):
                        operation()
                self.assertEqual(AnswerRevision.objects.count(), 1)

    def test_enforced_composition_missing_citation_schema_cannot_approve_existing_answer(self):
        draft = self.cited()
        installed = [
            app for app in settings.INSTALLED_APPS if not app.startswith("apps.case_citations")
        ]
        with override_settings(INSTALLED_APPS=installed):
            with self.assertRaisesMessage(cases.CaseConflict, "citation_schema_unavailable"):
                self.decide(draft)
            self.assertFalse(CaseDecision.objects.exists())
            # Feature-off legacy compositions retain their optional-app contract.
            with override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=False):
                self.assertEqual(self.decide(draft)["status"], "ANSWERED")
