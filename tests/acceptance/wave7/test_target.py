"""Pure safety checks: reject another lane/disabled target before any DB I/O."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.intake_workflow import guards as g, contracts as c
from .target import require_lane_configuration


class LanePreflightTests(unittest.TestCase):
    def configure(self, base="wave7_synthetic_e6_pure"):
        return SimpleNamespace(WAVE7_SCOPE=c.SYNTHETIC_SCOPE, WAVE7_SOURCE_CONFIG_ID=c.SOURCE_CONFIG_ID,
            WAVE7_BASE_DATABASE_NAME=base, WAVE7_TEST_DATABASE_NAME="test_"+base,
            DATABASES={"default": {"ENGINE":"django.db.backends.postgresql", "HOST":"127.0.0.1",
                "PORT":"55476", "USER":c.DATABASE_ROLE, "NAME":base, "TEST":{"NAME":"test_"+base}}})

    def setUp(self):
        self.env=patch.dict(os.environ, {"FATWA_WAVE7_E6_ACCEPTANCE":"1",
            "FATWA_WAVE7_SYNTHETIC_WRITES":"1", "FATWA_PRODUCTION":"0"}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.io=patch.object(g,"_connection",side_effect=AssertionError("No connection during configuration"))
        self.io.start(); self.addCleanup(self.io.stop)

    def test_own_explicit_config_is_accepted_without_connection(self):
        with patch.object(g,"settings",self.configure()):
            self.assertEqual(require_lane_configuration().base_name,"wave7_synthetic_e6_pure")

    def test_missing_lane_acknowledgement_rejects_before_shared_guard_or_io(self):
        os.environ.pop("FATWA_WAVE7_E6_ACCEPTANCE")
        with patch.object(g,"validate_write_configuration",side_effect=AssertionError("Too early")):
            with self.assertRaises(g.SyntheticWriteDenied) as caught:
                require_lane_configuration()
        self.assertEqual(caught.exception.code,"E6_ACCEPTANCE_OPT_IN_REQUIRED")

    def test_other_lane_target_is_rejected_without_connection(self):
        with patch.object(g,"settings",self.configure("wave7_synthetic_e5_sibling")):
            with self.assertRaises(g.SyntheticWriteDenied) as caught:
                require_lane_configuration()
        self.assertEqual(caught.exception.code,"E6_DEDICATED_DATABASE_REQUIRED")

    def test_shared_production_flags_and_connection_override_still_reject(self):
        with patch.object(g,"settings",self.configure()):
            for update in [{"FATWA_PRODUCTION":"1"},{"FATWA_WAVE7_SYNTHETIC_WRITES":"0"},
                           {"DATABASE_URL":"postgresql://forbidden.invalid/synthetic"}]:
                with self.subTest(keys=list(update)),patch.dict(os.environ,update),self.assertRaises(g.SyntheticWriteDenied):
                    require_lane_configuration()
