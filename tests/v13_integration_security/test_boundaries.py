"""Adversarial checks of integrator-owned V13 boundaries, not an app-wide audit."""

from dataclasses import replace
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.answer_media import services as media
from apps.casework import services as cases
from apps.source_rights.tests import Authority as RightsAuthority
from apps.timed_citations.tests import Fixture
from tests.casework import test_v13_timed_bindings as bindings


@override_settings(**bindings.FEATURES)
class TimedFinalCallbackTests(Fixture, TransactionTestCase):
    approve = bindings.TimedBindingsTests.approve
    approved = bindings.TimedBindingsTests.approved
    release = bindings.TimedBindingsTests.release

    def setUp(self):
        super().setUp()
        policy = override_settings(
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"])
        )
        policy.enable()
        self.addCleanup(policy.disable)

    def test_staff_revocation_in_final_deadline_callback_denies_private_bytes(self):
        self.approved()
        original = self.rights.grant_deadline
        called = []

        def revoke(**kwargs):
            import inspect

            value = original(**kwargs)
            # These calls execute inside the existing authorized canonical case
            # lock. Change the real configured identity directory, not persisted
            # SQL or an unauthorized external policy writer.
            caller = inspect.currentframe().f_back.f_code.co_name
            called.append(caller)
            if caller == "_rights" and inspect.currentframe().f_back.f_back.f_code.co_name == "for_locked_answer":
                self.directory.identities["editor"] = replace(
                    self.directory.identities["editor"], active=False
                )
            return value

        with patch.object(self.rights, "grant_deadline", new=revoke):
            with self.assertRaises(cases.CaseConflict):
                media.staff_read(part_id=str(self.part.pk), subject_id="editor",
                                 provider=self.directory, synthetic_fixtures_only=True)
        self.assertIn("_rights", called)
        self.assertFalse(self.directory.identities["editor"].active)

    def test_cite_revocation_in_final_deadline_callback_denies_requester_bytes(self):
        self.approved()
        self.release()
        original = self.rights.grant_deadline

        def revoke(**kwargs):
            import inspect

            value = original(**kwargs)
            if (inspect.currentframe().f_back.f_code.co_name == "_rights"
                    and inspect.currentframe().f_back.f_back.f_code.co_name == "for_locked_answer"
                    and kwargs["action"] == "CITE"):
                self.rights.actions.clear()
            return value

        with patch.object(self.rights, "grant_deadline", new=revoke):
            with self.assertRaises(cases.CaseConflict):
                media.requester_read(
                    token=self.receipt["token"], part_id=str(self.part.pk),
                    synthetic_fixtures_only=True,
                )
        self.assertEqual(self.rights.actions, set(), "the final retained callback must execute")

    def test_no_policy_deadline_callback_after_validated_hook_returns(self):
        from apps.timed_citations import services as timed

        self.approved()
        self.release()
        original_hook = timed.for_locked_answer
        original_deadline = self.rights.grant_deadline
        completed = []
        late = []

        def hook(**kwargs):
            value = original_hook(**kwargs)
            completed.append(True)
            return value

        def deadline(**kwargs):
            if completed:
                late.append(kwargs["action"])
            return original_deadline(**kwargs)

        with patch.object(timed, "for_locked_answer", new=hook), patch.object(
            self.rights, "grant_deadline", new=deadline
        ):
            result = media.requester_read(
                token=self.receipt["token"], part_id=str(self.part.pk),
                synthetic_fixtures_only=True,
            )
        self.assertTrue(completed)
        self.assertEqual(late, [], "a deadline callback ran after final authority checks")
        self.assertEqual(result["raw"], self.audio["raw"])

    def test_deadline_expiring_after_bytes_assembled_still_denies_requester_read(self):
        import inspect
        from datetime import timedelta

        self.approved()
        self.release()
        original = media.raw_for_part
        assembled = []

        def expire(row):
            value = original(row)
            if inspect.currentframe().f_back.f_code.co_name == "requester_read":
                assembled.append(value)
                clock = patch("django.utils.timezone.now", return_value=self.rights.valid_until + timedelta(seconds=1))
                clock.start()
                self.addCleanup(clock.stop)
            return value

        with patch.object(media, "raw_for_part", new=expire):
            with self.assertRaises(cases.CaseConflict):
                media.requester_read(
                    token=self.receipt["token"], part_id=str(self.part.pk),
                    synthetic_fixtures_only=True,
                )
        self.assertEqual(assembled, [self.audio["raw"]])

    def test_retained_final_cite_callback_cannot_revoke_then_open_audio_or_inspect(self):
        import inspect

        from apps.timed_citations import services as timed

        row = self.approved()
        original = self.rights.grant_deadline
        for operation, parent in (("audio", "open_audio"), ("inspect", "_source")):
            with self.subTest(operation=operation):
                self.rights.actions = {"READ_MEDIA", "CITE"}
                attacked = []

                def revoke(**kwargs):
                    value = original(**kwargs)
                    frame = inspect.currentframe().f_back
                    if (frame.f_code.co_name == "_rights"
                            and frame.f_back.f_code.co_name == parent
                            and kwargs["action"] == "CITE"):
                        attacked.append(kwargs["action"])
                        self.rights.actions.clear()
                    return value

                with patch.object(self.rights, "grant_deadline", new=revoke):
                    with self.assertRaises(cases.CaseConflict):
                        if operation == "audio":
                            timed.open_audio(**self.common, citation_id=row["id"])
                        else:
                            timed.inspect_source(**self.common, kind="ATTACHMENT",
                                                 source_id=self.attachment["id"])
                self.assertEqual(attacked, ["CITE"])
