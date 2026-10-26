"""Catch false-green reports, missing reasons and accidental authorization."""

import importlib
import io
import json
import os
import subprocess
import sys
import unicodedata
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apps.permission_lab import services as lab
from apps.permission_lab import sources
from apps.policy_gap_engine import services as gap

ROOT = Path(__file__).resolve().parents[2]


class ProbeTests(unittest.TestCase):
    def runner(self):
        try:
            return importlib.import_module("tools.fast8_permission_probes.runner")
        except ModuleNotFoundError:
            self.fail("Executable FAST8 permission regression runner is absent")

    def test_fixed_suite_runs_real_services_and_records_all_denials(self):
        report = self.runner().run_suite()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["counts"], {"passed": 27, "failed": 0, "not_run": 0})
        self.assertEqual(len({row["id"] for row in report["results"]}), 27)
        for row in report["results"]:
            with self.subTest(scenario=row["id"]):
                self.assertEqual(row["policy_gap_engine"]["effect"], "DENY")
                self.assertIs(row["policy_gap_engine"]["allowed"], False)
                self.assertIn("DENY_DEFAULT", row["policy_gap_engine"]["reason_codes"])
                self.assertEqual(row["status"], "PASS")
        self.assertEqual(report["case_authorization_adapter"], "NOT_CONNECTED")
        self.assertEqual(report["owner_source_acceptance"], "NOT_RUN")
        self.assertEqual(report["policy_approval"], "OWNER_APPROVAL_PENDING")

    def test_denial_without_expected_reason_is_a_regression(self):
        runner = self.runner()
        real = gap.evaluate

        def omit_reason(request):
            result = real(request)
            return SimpleNamespace(
                effect=result.effect,
                allowed=result.allowed,
                valid_combination=result.valid_combination,
                reasons=tuple(r for r in result.reasons if r.code != "UNKNOWN_ACTOR"),
            )

        with patch.object(gap, "evaluate", side_effect=omit_reason):
            report = runner.run_suite(("impersonation_superuser",))
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["counts"]["failed"], 1)

    def test_unicode_normalization_impersonation_is_detected(self):
        runner = self.runner()
        real = lab.evaluate

        def normalized(actor, action, resource):
            return real(unicodedata.normalize("NFKC", actor), action, resource)

        with patch.object(lab, "evaluate", side_effect=normalized):
            report = runner.run_suite(("fullwidth_actor",))
        self.assertEqual(report["status"], "FAIL")

    def test_allow_regression_is_reported_verbatim_not_replaced_by_deny(self):
        runner = self.runner()
        original = lab.evaluate("MUFTI", "synthetic::catalog.inspect", "synthetic::catalog")
        allowed = SimpleNamespace(
            effect="ALLOW",
            allowed=True,
            reasons=original.reasons,
            valid_combination=True,
            candidate_roles=original.candidate_roles,
            workflow_target=original.workflow_target,
        )
        with patch.object(lab, "evaluate", return_value=allowed):
            report = runner.run_suite(("candidate_still_denied",))
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["results"][0]["permission_lab"]["effect"], "ALLOW")
        self.assertIs(report["results"][0]["permission_lab"]["allowed"], True)

    def test_missing_real_source_never_counts_as_a_successful_attack(self):
        runner = self.runner()
        with patch.object(
            sources, "load_inventory", side_effect=sources.SourceUnavailable("secret")
        ):
            report = runner.run_suite()
        self.assertEqual(report["status"], "NOT_RUN")
        self.assertEqual(report["counts"], {"passed": 0, "failed": 0, "not_run": 27})
        self.assertNotIn("secret", json.dumps(report))

    def test_source_fault_injections_restore_loader_and_preserve_bundle_bytes(self):
        runner = self.runner()
        root = Path(sources.__file__).parent / "upstream"
        before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
        original_open = Path.open
        report = runner.run_suite(("substitute_inventory", "substitute_validator"))
        self.assertEqual(report["status"], "PASS")
        self.assertIs(Path.open, original_open)
        self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()})
        self.assertEqual(sources.load_inventory()["fixture_kind"], "SYNTHETIC")
        for row in report["results"]:
            self.assertEqual(row["permission_lab"]["outcome"], "SOURCE_UNAVAILABLE")
            self.assertIsNone(row["permission_lab"]["effect"])

    def test_identity_rejections_are_separate_from_policy_and_preserve_state(self):
        report = self.runner().run_suite(
            (
                "stale_case_key",
                "different_source_sha",
                "different_payload_sha",
                "duplicate_external_id_substitution",
                "reference_source_substitution",
            )
        )
        self.assertEqual(report["status"], "PASS")
        for row in report["results"]:
            boundary = row["domain_boundary"]
            self.assertEqual(boundary["reason_codes"], ["event: source_identity_mismatch"])
            self.assertIs(boundary["accepted"], False)
            self.assertIs(boundary["state_unchanged"], True)
            self.assertEqual(boundary["before_sha256"], boundary["after_sha256"])

    def test_duplicate_external_ids_reject_both_rows_without_joining(self):
        report = self.runner().run_suite(("duplicate_external_id",))
        boundary = report["results"][0]["domain_boundary"]
        self.assertEqual(boundary["row_ordinals"], [1, 4])
        self.assertEqual(boundary["statuses"], ["BLOCKED_INVALID", "BLOCKED_INVALID"])
        self.assertEqual(boundary["reason_codes"], ["duplicate_id"])
        self.assertIs(boundary["source_preserved"], True)

    def test_replay_acceptance_regression_cannot_be_hidden_by_policy_denial(self):
        runner = self.runner()
        real = runner.workflow.replay

        def accept(request):
            result = real(request)
            result["steps"][0]["accepted"] = True
            return result

        with patch.object(runner.workflow, "replay", side_effect=accept):
            report = runner.run_suite(("different_source_sha",))
        self.assertEqual(report["status"], "FAIL")

    def test_removed_source_pin_check_is_a_failure_not_a_green_denial(self):
        runner = self.runner()
        root = Path(sources.__file__).parent / "upstream"

        def unchecked(name):
            return (root / name).read_bytes()

        # JSON trailing whitespace is valid, so disable only the hash checker
        # and fault the validator Python bytes, retaining real contract parsing.
        with patch.object(sources, "_pinned_bytes", side_effect=unchecked):
            report = runner.run_suite(("substitute_validator",))
        self.assertEqual(report["status"], "FAIL")

    def test_late_source_loss_invalidates_otherwise_successful_report(self):
        runner = self.runner()
        real = gap.load_evidence
        calls = 0

        def unavailable_at_end():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise sources.SourceUnavailable("late source loss")
            return real()

        with patch.object(gap, "load_evidence", side_effect=unavailable_at_end):
            report = runner.run_suite(("candidate_still_denied",))
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["reason_codes"], ["SOURCE_CHANGED_DURING_RUN"])

    def test_unexpected_exception_is_failed_without_leaking_details(self):
        runner = self.runner()
        with patch.object(gap, "evaluate", side_effect=RuntimeError("private-path")):
            report = runner.run_suite(("candidate_still_denied",))
        self.assertEqual(report["status"], "FAIL")
        self.assertNotIn("private-path", json.dumps(report))

    def test_offline_deterministic_report_needs_no_django_setup(self):
        runner = self.runner()
        from django.conf import settings

        configured = settings.configured
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            first = runner.run_suite()
            second = runner.run_suite()
        self.assertEqual(first, second)
        self.assertEqual(settings.configured, configured)
        self.assertEqual(first["status"], "PASS")

    def test_selection_is_bounded_and_cannot_supply_external_records(self):
        runner = self.runner()
        for value in (
            [],
            (),
            ("unknown",),
            ("candidate_still_denied",) * 65,
            ("candidate_still_denied",) * 2,
            ([],),
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "INVALID_SCENARIO_SELECTION"):
                    runner.run_suite(value)


class CliTests(unittest.TestCase):
    def cli(self, *args):
        env = os.environ.copy()
        env.pop("DJANGO_SETTINGS_MODULE", None)
        env["PYTHONIOENCODING"] = "ascii"
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast8_permission_probes", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_cli_runs_fixed_machine_readable_report(self):
        result = self.cli("--synthetic-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["counts"]["passed"], 27)
        self.assertEqual(result.stderr, b"")

    def test_cli_rejects_external_inputs_abbreviations_and_missing_ack(self):
        for args in (
            (),
            ("--synthetic-on",),
            ("--synthetic-only", "--input", "secret.json"),
            ("--synthetic-only", "--actor", "MUFTI"),
        ):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")

    def test_cli_single_selection_and_list_do_not_claim_full_coverage(self):
        result = self.cli("--synthetic-only", "--scenario", "stale_case_key")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"]["passed"], 1)
        listing = self.cli("--synthetic-only", "--list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual(len(json.loads(listing.stdout)["scenarios"]), 27)

    def test_cli_failure_exit_mapping(self):
        ProbeTests().runner()
        from tools.fast8_permission_probes import __main__ as cli

        for status, expected in (("FAIL", 1), ("NOT_RUN", 3)):
            output = io.BytesIO()
            with (
                self.subTest(status=status),
                patch.object(cli, "run_suite", return_value={"status": status}),
                patch.object(cli.sys, "stdout", SimpleNamespace(buffer=output)),
            ):
                actual = cli.main(["--synthetic-only"])
            self.assertEqual(actual, expected)
            self.assertEqual(json.loads(output.getvalue())["status"], status)
