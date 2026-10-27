from unittest import TestCase
from unittest.mock import patch

from tools.fast9_case_source_join.postgresql import require_target, run


class PreflightTests(TestCase):
    def target(self):
        return {
            "DJANGO_SETTINGS_MODULE": "config.settings.wave7_test",
            "FATWA_PRODUCTION": "0",
            "FATWA_WAVE7_SYNTHETIC_WRITES": "1",
            "FATWA_WAVE7_SYNTHETIC_READS": "1",
            "FATWA_FAST9_CASE_SOURCE_JOIN_PG": "1",
            "PGHOST": "127.0.0.1",
            "PGPORT": "5432",
            "PGDATABASE": "wave7_synthetic_fast9_case_source_join",
            "PGTESTDATABASE": "test_wave7_synthetic_fast9_case_source_join",
            "PGUSER": "wave7_synthetic",
            "PGPASSWORD": "fabricated-test-only",
        }

    def test_wrong_or_absent_identity_rejected_before_django_setup(self):
        for key in self.target():
            env = self.target()
            env.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_target(env)
        for key, value in (
            ("PGDATABASE", "live"),
            ("PGTESTDATABASE", "test_live"),
            ("PGUSER", "postgres"),
            ("PGHOST", "db.example.invalid"),
            ("FATWA_PRODUCTION", "1"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_target({**self.target(), key: value})

    def test_authorized_exact_configuration_is_read_only_preflight(self):
        env = self.target()
        before = dict(env)
        require_target(env)
        self.assertEqual(env, before)

    def test_runner_without_opt_in_never_initializes_django_or_connects(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("django.setup", side_effect=AssertionError("must not initialize")),
            patch("socket.socket", side_effect=AssertionError("must not connect")),
        ):
            self.assertEqual(run(), 2)
