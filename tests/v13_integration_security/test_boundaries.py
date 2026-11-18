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
            if caller == "_answer_timed":
                self.directory.identities["editor"] = replace(
                    self.directory.identities["editor"], active=False
                )
            return value

        with patch.object(self.rights, "grant_deadline", new=revoke):
            with self.assertRaises(cases.CaseConflict):
                media.staff_read(part_id=str(self.part.pk), subject_id="editor",
                                 provider=self.directory, synthetic_fixtures_only=True)
        self.assertIn("_answer_timed", called)
