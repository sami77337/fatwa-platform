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
