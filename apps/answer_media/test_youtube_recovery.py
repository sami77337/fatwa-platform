from django.test import TransactionTestCase

from . import youtube_recovery_support as recovery


class YouTubeRecoveryTests(TransactionTestCase):
    def test_real_external_reference_restore_and_current_denials(self):
        pins = recovery.populate()
        result = recovery.verify_restored(pins)
        self.assertEqual(result["denial_checks"], {"missing_authority": 1, "inactive_identity": 1})
        self.assertIs(result["positive_reads_after_denial"], True)
