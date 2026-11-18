"""No database, browser, network, probe, sleep or real timer required."""

import ast
import json
from contextlib import ExitStack, nullcontext
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from playwright._impl._connection import format_call_log
from playwright._impl._helper import parse_error
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tests.editorial_workbench.launch_diagnostics import (
    MESSAGE_LIMIT,
    launch_browser,
    observations,
    observe_error,
)


class LaunchDiagnosticsTests(TestCase):
    def test_pinned_162_error_payload_and_private_log_contract(self):
        self.assertEqual(version("playwright"), "1.62.0")
        private = "PRIVATE_FIXTURE_73f91"
        error = parse_error(
            {"name": "TimeoutError", "message": "Timeout 10000ms exceeded.", "stack": private},
            format_call_log(
                [
                    f"  - <launching> /private/{private} --token={private}",
                    "  - <launched> pid=87654321",
                    f"  - [pid=87654321][err] https://private.invalid/{private}",
                    "  - [pid=87654321][err] No usable sandbox!",
                    "  - [pid=87654321][err] private.so: error while loading shared libraries:",
                    "  - [pid=87654321] <process did exit: exitCode=null, signal=SIGKILL>",
                ]
            ),
        )
        self.assertIsInstance(error, PlaywrightTimeoutError)
        report = observations()
        observe_error(error, report)
        for key in (
            "launching_marker",
            "launched_marker",
            "exit_marker",
            "sandbox_error_marker",
            "loader_error_marker",
        ):
            self.assertEqual(report[key], "OBSERVED")
        self.assertEqual(report["exit_kind"], "SIGNAL")
        serialized = json.dumps(report)
        for secret in (
            private,
            "87654321",
            "private.invalid",
            "/private/",
            "SIGKILL",
            "private.so",
            "Timeout 10000ms exceeded",
        ):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("cause", report)

    def test_missing_or_unstructured_markers_stay_unknown(self):
        report = observations()
        observe_error(
            PlaywrightTimeoutError(
                "Timeout 10000ms exceeded. URL=https://x.invalid/<launched> pid=12\n"
                "No usable sandbox!\n<process did exit: exitCode=9, signal=null>"
            ),
            report,
        )
        self.assertTrue(all(report[k] == "UNKNOWN" for k in report if k.endswith("marker")))
        self.assertEqual(report["exit_kind"], "UNKNOWN")

    def test_exit_categories_are_bounded_and_do_not_infer_cause(self):
        for code, signal, expected in (
            ("0", "null", "ZERO"),
            ("9", "null", "NONZERO"),
            ("null", "null", "UNKNOWN"),
            ("null", "SIGTERM", "SIGNAL"),
        ):
            with self.subTest(expected=expected):
                report = observations()
                observe_error(
                    PlaywrightError(
                        f"[pid=123] <process did exit: exitCode={code}, signal={signal}>"
                    ),
                    report,
                )
                self.assertEqual(report["exit_marker"], "OBSERVED")
                self.assertEqual(report["exit_kind"], expected)

    def test_oversize_message_tail_is_not_scanned_or_serialized(self):
        report = observations()
        observe_error(
            PlaywrightTimeoutError("x" * MESSAGE_LIMIT + "\n<launched> pid=87654321\nTAIL_PRIVATE"),
            report,
        )
        self.assertTrue(report["message_truncated"])
        self.assertEqual(report["launched_marker"], "UNKNOWN")
        self.assertLess(len(json.dumps(report)), 800)
        self.assertNotIn("TAIL_PRIVATE", json.dumps(report))

    def test_non_playwright_error_is_not_read(self):
        report = observations()
        before = report.copy()
        observe_error(RuntimeError("<launched> pid=123"), report)
        self.assertEqual(report, before)

    def test_version_is_numeric_or_unknown_only(self):
        for value in ("private/version", "1.62.0+PRIVATE", "1.62.0\nPRIVATE", "9" * 100_000):
            with patch("tests.editorial_workbench.launch_diagnostics.version", return_value=value):
                self.assertEqual(observations()["playwright_version"], "UNKNOWN")
        with patch(
            "tests.editorial_workbench.launch_diagnostics.version", side_effect=RuntimeError
        ):
            self.assertEqual(observations()["playwright_version"], "UNKNOWN")

    def launch_fixture(self, *, error=None):
        browser = object()
        launch = Mock(return_value=browser, side_effect=error)
        factory = Mock(
            return_value=nullcontext(SimpleNamespace(chromium=SimpleNamespace(launch=launch)))
        )
        return browser, launch, factory

    def test_success_uses_one_identical_launch_and_monotonic_phase_measurements(self):
        browser, launch, factory = self.launch_fixture()
        report = observations()
        clock = Mock(side_effect=[20, 20.125, 21, 21.75])
        with ExitStack() as stack:
            result = launch_browser(stack, factory, "/usr/bin/google-chrome", report, clock=clock)
        self.assertIs(result, browser)
        factory.assert_called_once_with()
        launch.assert_called_once_with(
            executable_path="/usr/bin/google-chrome", chromium_sandbox=True, timeout=10_000
        )
        self.assertEqual(clock.call_count, 4)
        self.assertEqual(report["driver_elapsed_ms"], 125)
        self.assertEqual(report["launch_elapsed_ms"], 750)
        self.assertTrue(report["launch_returned"])

    def test_timeout_rethrows_identical_error_without_retry_or_journey(self):
        error = PlaywrightTimeoutError("Timeout 10000ms exceeded.\n<launched> pid=123")
        _, launch, factory = self.launch_fixture(error=error)
        journey = Mock()
        report = observations()
        clock = Mock(side_effect=[1, 1.25, 2, 12.125])
        with ExitStack() as stack, self.assertRaises(PlaywrightTimeoutError) as caught:
            launch_browser(stack, factory, "/usr/bin/google-chrome", report, clock=clock)
            journey()
        self.assertIs(caught.exception, error)
        launch.assert_called_once_with(
            executable_path="/usr/bin/google-chrome", chromium_sandbox=True, timeout=10_000
        )
        journey.assert_not_called()
        self.assertEqual(report["launch_elapsed_ms"], 10_125)
        self.assertFalse(report["launch_returned"])
        self.assertEqual(report["launched_marker"], "OBSERVED")

    def test_driver_entry_failure_does_not_attempt_launch(self):
        context = Mock()
        error = RuntimeError("PRIVATE")
        context.__enter__ = Mock(side_effect=error)
        context.__exit__ = Mock()
        factory = Mock(return_value=context)
        report = observations()
        with ExitStack() as stack, self.assertRaises(RuntimeError) as caught:
            launch_browser(stack, factory, "unused", report, clock=Mock(side_effect=[1, 1.5]))
        self.assertIs(caught.exception, error)
        self.assertEqual(report["driver_elapsed_ms"], 500)
        self.assertIsNone(report["launch_elapsed_ms"])
        self.assertEqual(report["launched_marker"], "UNKNOWN")

    def test_non_playwright_launch_failure_propagates_unchanged(self):
        error = RuntimeError("PRIVATE")
        _, launch, factory = self.launch_fixture(error=error)
        report = observations()
        with ExitStack() as stack, self.assertRaises(RuntimeError) as caught:
            launch_browser(stack, factory, "unused", report, clock=Mock(side_effect=[1, 2, 3, 4]))
        self.assertIs(caught.exception, error)
        self.assertEqual(launch.call_count, 1)
        self.assertEqual(report["launch_elapsed_ms"], 1000)
        self.assertEqual(report["exit_marker"], "UNKNOWN")

    def test_reporting_bounds_do_not_change_launch_timeout(self):
        for end, expected in ((-1, 0), (10_000, 600_000), (float("inf"), None)):
            with self.subTest(end=end):
                _, launch, factory = self.launch_fixture()
                report = observations()
                with ExitStack() as stack:
                    launch_browser(
                        stack, factory, "unused", report, clock=Mock(side_effect=[0, 0, 0, end])
                    )
                self.assertEqual(report["launch_elapsed_ms"], expected)
                self.assertEqual(launch.call_args.kwargs["timeout"], 10_000)

    def test_real_harness_wires_and_prints_only_one_launch_observation(self):
        # Inspect wiring without importing Django or executing the product journey.
        source = Path(__file__).with_name("return_preparation_browser.py").read_text()
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        launch_calls = [
            node
            for node in calls
            if isinstance(node.func, ast.Name) and node.func.id == "launch_browser"
        ]
        self.assertEqual(len(launch_calls), 1)
        self.assertEqual(len(launch_calls[0].args), 4)
        self.assertIn('"startup_diagnostics": receipt.get("startup_diagnostics")', source)
        self.assertIn('"category"] = "playwright_timeout"', source)
        self.assertNotIn("chromium.launch(", source)
