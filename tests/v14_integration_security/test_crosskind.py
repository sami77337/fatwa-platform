"""A later PDF policy callback must not leave earlier audio rights usable.

Real canonical PDF/timed annotations share one current answer. Only the explicit
media-policy callback is wrapped; source bytes, guards and approval/use services
are not mocked. This is callback-policy withdrawal, not concurrent SQL evidence.
"""

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media.models import PrivateAnswerRelease
from apps.answer_media.tests import audio_fixture
from apps.case_attachments import services as attachments
from apps.casework import services as cases
from apps.casework.models import Case, CaseDecision
from apps.pdf_citations import tests as pdf_fixtures
from apps.platform_recovery import maintenance
from apps.private_media.filesystem import FileSystemStorage
from apps.timed_citations import services as timed
from tests.casework import test_v13_timed_bindings as shared
from tests.casework import test_v14_pdf_bindings as bindings


@override_settings(**{**bindings.FEATURES, "FATWA_TIMED_CITATIONS_ENABLED": True})
class CrossKindPolicyTests(pdf_fixtures.Fixture, TransactionTestCase):
    approve = shared.TimedBindingsTests.approve
    release = shared.TimedBindingsTests.release

    def setUp(self):
        temporary = TemporaryDirectory(prefix="v14-crosskind-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        storage = FileSystemStorage(self.root / "private", synthetic_fixtures_only=True)
        storage_config = override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage)
        storage_config.enable()
        self.addCleanup(storage_config.disable)
        super().setUp()
        self.rights.valid_until = timezone.now() + timedelta(minutes=10)
        current = Case.objects.get(pk=self.receipt["case_id"])
        self.audio = attachments.upload(
            token=self.receipt["token"],
            **audio_fixture(),
            expected_revision=current.revision,
            synthetic_fixtures_only=True,
        )
        self.audio_key = ("ATTACHMENT", self.audio["id"], self.audio["sha256"])
        self.rights.pins.add(self.audio_key)
        self.save()  # New evidence requires a current answer, not old parallel state.
        self.confirm(self.propose())
        pin = timed.inspect_source(**self.common, kind="ATTACHMENT", source_id=self.audio["id"])
        current = Case.objects.get(pk=self.receipt["case_id"])
        row = timed.propose(
            **self.common,
            source_pin=pin,
            start_ms=0,
            end_ms=min(100, pin["duration_ms"]),
            reason="Synthetic human-confirmed audio locator",
            expected_revision=current.revision,
            expected_evidence_version=current.evidence_version,
        )
        timed.act(**self.common, citation_id=row["id"], action="CONFIRM", confirmed=True)
        control = self.root / "control"
        control.mkdir(mode=0o700)
        maintenance.initialize(root=control, storage=storage, synthetic_fixtures_only=True)
        config = override_settings(
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            FATWA_RECOVERY_MAINTENANCE_ROOT=control,
        )
        config.enable()
        self.addCleanup(config.disable)
        self.attacks = 0

    def revoke_audio_while_reading_pdf(self, **kwargs):
        resource = kwargs["resource"]
        if resource.identifier == self.attachment["id"] and not self.attacks:
            self.assertIn(self.audio_key, self.rights.pins)
            self.rights.pins.remove(self.audio_key)
            self.attacks += 1
        return self.original_permits(**kwargs)

    def denied_after_callback(self, operation):
        self.original_permits = self.rights.permits
        denied = False
        with patch.object(self.rights, "permits", side_effect=self.revoke_audio_while_reading_pdf):
            try:
                operation()
            except cases.CaseConflict:
                denied = True
        self.assertEqual(
            self.attacks, 1, "PDF callback must actually withdraw earlier audio rights"
        )
        self.assertNotIn(self.audio_key, self.rights.pins)
        self.assertTrue(denied, "Later PDF callback left revoked audio usable by the whole answer")

    def test_current_mixed_answer_allows_human_approval_and_release_without_revocation(self):
        self.approve()
        self.assertTrue(self.release()["available"])
        self.assertEqual(CaseDecision.objects.count(), 1)
        self.assertEqual(PrivateAnswerRelease.objects.count(), 1)

    def test_pdf_callback_revoking_audio_blocks_canonical_approval(self):
        self.denied_after_callback(self.approve)
        self.assertFalse(CaseDecision.objects.exists())

    def test_pdf_callback_revoking_audio_blocks_new_private_release(self):
        self.approve()
        self.denied_after_callback(self.release)
        self.assertFalse(PrivateAnswerRelease.objects.exists())

    def test_unversioned_or_malformed_media_policy_cannot_approve(self):
        for epoch in (None, "", True, 1, "x" * 1001):
            with (
                self.subTest(epoch=epoch),
                patch.object(self.rights, "media_projection_epoch", return_value=epoch),
                self.assertRaisesMessage(cases.CaseConflict, "media_policy_snapshot_required"),
            ):
                self.approve()
            self.assertFalse(CaseDecision.objects.exists())

    def test_revocation_after_all_locator_checks_rolls_back_approval(self):
        from apps.answer_media import services as media

        validate = media.validate_for_approval
        attacks = []

        def revoke(answer):
            result = validate(answer)
            self.rights.pins.remove(self.audio_key)
            attacks.append(1)
            return result

        with patch.object(media, "validate_for_approval", side_effect=revoke):
            with self.assertRaisesMessage(cases.CaseConflict, "media_policy_changed"):
                self.approve()
        self.assertEqual(attacks, [1])
        self.assertFalse(CaseDecision.objects.exists())

    def test_policy_replacement_with_equal_epoch_cannot_approve(self):
        from copy import copy

        from django.conf import settings

        from apps.answer_media import services as media

        validate = media.validate_for_approval
        replacement = copy(self.rights)
        self.assertEqual(replacement.media_projection_epoch(), self.rights.media_projection_epoch())
        attacks = []

        def swap(answer):
            result = validate(answer)
            settings.FATWA_RESEARCH_WORKSPACE_RIGHTS = replacement
            attacks.append(1)
            return result

        with patch.object(media, "validate_for_approval", side_effect=swap):
            with self.assertRaisesMessage(cases.CaseConflict, "media_policy_changed"):
                self.approve()
        self.assertEqual(attacks, [1])
        self.assertFalse(CaseDecision.objects.exists())

    def test_library_return_boundary_rejects_revocation_after_all_item_checks(self):
        from apps.experimental_publication.tests import Authority
        from apps.library_preview import services as preview
        from apps.source_rights.tests import Authority as RightsAuthority

        self.approve()
        authority = override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=Authority(self.receipt["public_ref"]),
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"]),
        )
        authority.enable()
        self.addCleanup(authority.disable)
        self.edition = lambda: shared.TimedBindingsTests.edition(self)
        shared.TimedBindingsTests.published(self)
        self.assertEqual(preview.browse()["total"], 1)
        recheck = preview._recheck
        attacks = []

        def revoke(selected):
            recheck(selected)
            if not attacks:
                self.rights.pins.remove(self.audio_key)
                attacks.append(1)

        with patch.object(preview, "_recheck", side_effect=revoke):
            with self.assertRaises(preview.PreviewUnavailable):
                preview.browse()
        self.assertEqual(attacks, [1])
