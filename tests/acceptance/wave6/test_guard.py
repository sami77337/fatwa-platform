"""No-DB checks for the pre-creation destructive-test-resource guard."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.acceptance.wave6 import support


class DisposableDatabaseGuardTests(unittest.TestCase):
    def check_config(self, **changes):
        config = {"ENGINE": "django.db.backends.postgresql", "NAME": "e6_synthetic",
                  "HOST": "127.0.0.1", "TEST": {"NAME": "test_e6_synthetic"}}
        config.update(changes)
        with patch.object(support, "settings", SimpleNamespace(DATABASES={"default": config})):
            support.require_disposable_database()

    @patch.dict(os.environ, {"E6_SYNTHETIC_ONLY": "1"})
    def test_explicit_disposable_config_is_accepted(self):
        self.check_config()

    def test_missing_acknowledgement_fails(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            self.check_config()

    @patch.dict(os.environ, {"E6_SYNTHETIC_ONLY": "1"})
    def test_owner_or_sibling_database_names_fail(self):
        for name in ["fatwa_reference_dev", "b6_ephemeral", "", "test_e6_synthetic"]:
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.check_config(NAME=name)

    @patch.dict(os.environ, {"E6_SYNTHETIC_ONLY": "1"})
    def test_wrong_or_unspecified_test_database_fails(self):
        for value in [{}, {"NAME": "test_fatwa_reference_dev"}, {"NAME": "test_b6_ephemeral"}]:
            with self.subTest(test=value), self.assertRaises(RuntimeError):
                self.check_config(TEST=value)

    @patch.dict(os.environ, {"E6_SYNTHETIC_ONLY": "1"})
    def test_remote_or_hostname_database_targets_fail(self):
        for host in ["owner.invalid", "localhost", "", "::1"]:
            with self.subTest(host=host), self.assertRaises(RuntimeError):
                self.check_config(HOST=host)

    @patch.dict(os.environ, {"E6_SYNTHETIC_ONLY": "1"})
    def test_non_postgresql_engine_fails(self):
        with self.assertRaises(RuntimeError):
            self.check_config(ENGINE="django.db.backends.sqlite3")
