"""Helper contract before the independent fresh-target restore runner consumes it."""

from django.test import TransactionTestCase, override_settings

from . import recovery_support
from .test_support import FEATURES


@override_settings(**FEATURES)
class DerivativeRecoveryTests(TransactionTestCase):
    def test_nonempty_actual_output_history_requires_fresh_authority_for_every_read(self):
        pins = recovery_support.populate()
        result = recovery_support.verify_restored(pins)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["nonempty_tables"], 3)
        self.assertEqual(result["denied_read_count"], len(recovery_support.DENIALS))
        self.assertEqual(result["denial_checks"], dict.fromkeys(recovery_support.DENIALS, 1))
        self.assertEqual(result["processor_mode"], "LOCAL_FFMPEG")
