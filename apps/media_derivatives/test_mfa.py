"""Actual primary/TOTP session issuance composed with private background processing."""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.mufti_review.identity import IdentityUnavailable
from apps.research_workspace.rights import ResearchRights
from apps.staff_mfa import native_test_support as mfa_native
from apps.staff_mfa import services as mfa
from apps.staff_mfa import test_support as mfa_fixtures
from apps.staff_mfa.models import FactorRevocation, SessionAssurance
from apps.staff_sessions import integration as session_context
from apps.upload_security.test_support import configure_scanner

from . import execution, services
from . import test_http as native
from .authority import DerivativeAuthority
from .models import DerivativeEvent, DerivedOutput
from .test_execution import recording


class Authority(DerivativeAuthority):
    def __init__(self, ref):
        self.ref, self.denied = ref, set()
        self.until = timezone.now() + timedelta(minutes=30)

    def projection_epoch(self):
        return repr((self.ref, sorted(self.denied), self.until))

    def grant_deadline(self, **values):
        return self.until

    def permits(self, **values):
        return (
            values["provider_id"] == mfa_fixtures.Directory.provider_id
            and values["subject_id"] == "mufti"
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] == self.ref
            and values["task"] == "AUDIO_PLAYBACK"
            and values["source"]["kind"] == "ATTACHMENT"
            and values["action"] in {"CREATE", "EXECUTE", "READ", "RETRY", "CANCEL"}
            and values["action"] not in self.denied
            and timezone.now() < self.until
        )


class Rights(ResearchRights):
    def __init__(self, ref):
        self.ref, self.denied = ref, False

    def projection_epoch(self):
        return repr((self.ref, self.denied))

    def permits(self, **values):
        return (
            values["provider_id"] == mfa_fixtures.Directory.provider_id
            and values["subject_id"] == "mufti"
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] == self.ref
            and values["resource"].kind == "ATTACHMENT"
            and values["action"] == "READ_MEDIA"
            and not self.denied
        )


NATIVE = {**native.NATIVE, **mfa_fixtures.FEATURES}


@override_settings(**NATIVE)
class DerivativeMfaTests(mfa_native.NativeFixture, TransactionTestCase):
    # Reuse form mechanics, not another discovered TestCase or a forged session.
    open = native.NativeFixture.open
    enqueue = native.NativeFixture.enqueue
    output_url = native.NativeFixture.output_url
    execute_command = native.NativeFixture.execute_command
    denied_file = native.NativeFixture.denied_file

    def setUp(self):
        super().setUp()
        self.derivative_authority = Authority(self.receipt["public_ref"])
        self.rights = Rights(self.receipt["public_ref"])
        self.processor = execution.FFmpegProcessor("/usr/bin/ffmpeg", "/usr/bin/ffprobe")
        self.enterContext(
            override_settings(
                FATWA_MEDIA_DERIVATIVES_AUTHORITY=self.derivative_authority,
                FATWA_MEDIA_DERIVATIVES_PROCESSOR=self.processor,
                FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            )
        )
        configure_scanner(self)
        self.raw = recording()
        self.attachment = attachments.upload(
            token=self.receipt["token"],
            raw=self.raw,
            filename="synthetic-mfa-original.wav",
            media_type="audio/wav",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        self.client, _, self.factor, _ = self.enroll_login()
        self.job, _ = self.enqueue(self.client)
        self.worker = dict(
            case_id=self.receipt["case_id"],
            provider=self.directory,
            subject_id="mufti",
            job_id=self.job.pk,
            synthetic_fixtures_only=True,
        )

    def revoking(self):
        self.challenge = self.start(purpose="REVOKE")

    def revoke(self):
        with mfa.complete(self.challenge.id, code=self.otp(self.factor), **self.common()) as (
            grant,
            _,
        ):
            mfa.revoke(grant)

    def unchanged_original(self):
        self.assertEqual(
            bytes(CaseAttachment.objects.get(pk=self.attachment["id"]).original), self.raw
        )

    def test_current_actual_mfa_session_is_veto_only_and_worker_needs_no_request_lease(self):
        self.assertEqual(SessionAssurance.objects.count(), 1)
        self.assertEqual(SessionAssurance.objects.get().session_id, self.job.origin_session_id)
        with self.assertRaises(IdentityUnavailable):
            session_context.context()
        result = self.execute_command(self.job)
        self.assertEqual(result["state"], "READY")
        url = self.output_url(self.open(self.client), self.job)
        self.assertEqual(self.client.get(url).content, self.raw)
        self.rights.denied = True
        self.denied_file(self.client.get(url))
        self.rights.denied = False
        self.revoking()
        self.revoke()
        self.denied_file(self.client.get(url))
        self.unchanged_original()

    def test_revoked_factor_before_claim_cannot_start_the_real_processor(self):
        self.revoking()
        self.revoke()
        with patch.object(
            execution.FFmpegProcessor, "run", side_effect=AssertionError("processor reached")
        ):
            with self.assertRaises(cases.CaseConflict):
                services.run_job(**self.worker)
        self.assertEqual(FactorRevocation.objects.count(), 1)
        self.assertEqual(list(DerivativeEvent.objects.values_list("state", flat=True)), ["QUEUED"])
        self.assertEqual(DerivedOutput.objects.count(), 0)
        self.unchanged_original()

    def test_revoked_factor_after_actual_ffmpeg_discards_late_result(self):
        self.revoking()
        actual = execution.FFmpegProcessor.run
        reached = []

        def process(processor, *args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            result = actual(processor, *args, **kwargs)
            self.assertEqual(result.status, "READY")
            reached.append(True)
            self.revoke()
            return result

        with patch.object(execution.FFmpegProcessor, "run", process):
            with self.assertRaises(cases.CaseConflict):
                services.run_job(**self.worker)
        self.assertEqual(reached, [True])
        self.assertEqual(FactorRevocation.objects.count(), 1)
        self.assertEqual(DerivedOutput.objects.count(), 0)
        self.assertEqual(self.job.events.order_by("-sequence").first().state, "RUNNING")
        self.unchanged_original()

    def test_final_session_callback_factor_revocation_rolls_back_saved_result(self):
        self.revoking()
        reached = []

        def final(values):
            if values["action"] == "USE" and not reached and DerivedOutput.objects.exists():
                reached.append(True)
                self.revoke()

        self.session_authority.hook = final
        with self.assertRaises(cases.CaseConflict):
            services.run_job(**self.worker)
        self.assertEqual(reached, [True])
        self.assertEqual(DerivedOutput.objects.count(), 0)
        self.assertEqual(self.job.events.order_by("-sequence").first().state, "RUNNING")
        self.unchanged_original()

    def test_disabled_or_omitted_mfa_cannot_downgrade_a_saved_factor(self):
        without_app = [name for name in settings.INSTALLED_APPS if name != "apps.staff_mfa"]
        for changes in (
            {"FATWA_STAFF_MFA_ENABLED": False},
            {"FATWA_STAFF_MFA_ENABLED": False, "INSTALLED_APPS": without_app},
            {"INSTALLED_APPS": without_app},
            {"FATWA_STAFF_MFA_AUTHORITY": None},
            {"FATWA_STAFF_MFA_KEY": None},
        ):
            with self.subTest(changes=tuple(changes)):
                with override_settings(**changes):
                    with patch.object(
                        execution.FFmpegProcessor,
                        "run",
                        side_effect=AssertionError("processor reached"),
                    ):
                        with self.assertRaises(cases.CaseConflict):
                            services.run_job(**self.worker)
        self.assertEqual(self.job.events.count(), 1)
        self.assertEqual(DerivedOutput.objects.count(), 0)

    def test_last_mfa_use_callback_cannot_waive_original_read(self):
        reached = []

        def final(values):
            if values["action"] == "USE" and not reached and DerivedOutput.objects.exists():
                reached.append(True)
                self.rights.denied = True

        self.authority.hook = final
        with self.assertRaises(cases.CaseConflict):
            services.run_job(**self.worker)
        self.assertEqual(reached, [True])
        self.assertEqual(DerivedOutput.objects.count(), 0)
        self.assertEqual(self.job.events.order_by("-sequence").first().state, "RUNNING")
