"""A reaped Linux child can disappear between the liveness probe and stat read."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.acceptance.fastbuild import test_browser_supervisor as supervisor_tests


class ProcessProbeTests(unittest.TestCase):
    def probe(self, stat_result, *, kill_error=None):
        stat = Mock()
        stat.exists.return_value = True
        if isinstance(stat_result, Exception):
            stat.read_text.side_effect = stat_result
        else:
            stat.read_text.return_value = stat_result
        posix = SimpleNamespace(name="posix", kill=Mock(side_effect=kill_error))
        with (
            patch.object(supervisor_tests, "os", posix),
            patch.object(supervisor_tests, "Path", return_value=stat),
        ):
            return supervisor_tests.running(123)

    def test_reaped_between_exists_and_read_is_stopped(self):
        self.assertFalse(self.probe(FileNotFoundError("/proc/123/stat disappeared")))

    def test_live_child_is_still_running(self):
        self.assertTrue(self.probe("123 (synthetic-child) S 1 2 3"))

    def test_zombie_is_not_an_executing_child(self):
        self.assertFalse(self.probe("123 (synthetic-child) Z 1 2 3"))

    def test_missing_pid_is_stopped(self):
        self.assertFalse(self.probe("", kill_error=ProcessLookupError()))

    def test_permission_error_is_not_misreported_as_stopped(self):
        with self.assertRaises(PermissionError):
            self.probe(PermissionError("proc unavailable"))
