import hashlib
import json
import unittest
from pathlib import Path

from .analyze_b6 import EvidenceError, compare, parse

EVIDENCE = Path(__file__).with_name("evidence")
SHA = "1f08cbb7166f70ec340c495da33ccfc1eda9534e"


class B6EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.failed = (EVIDENCE / "134547992648.excerpt.log").read_bytes()
        self.passed = (EVIDENCE / "134548019306.excerpt.log").read_bytes()

    def reject(self, data, outcome="failure"):
        with self.assertRaises(EvidenceError):
            parse(data, expected_sha=SHA, outcome=outcome)

    def transform_report(self, transform, raw=None):
        lines = (raw or self.failed).decode().splitlines()
        for i, line in enumerate(lines):
            if "E6_BROWSER_EVIDENCE " in line:
                prefix, report = line.split("E6_BROWSER_EVIDENCE ", 1)
                report = json.loads(report)
                transform(report)
                lines[i] = prefix + "E6_BROWSER_EVIDENCE " + json.dumps(report)
        return ("\n".join(lines) + "\n").encode()

    def test_all_five_actual_excerpts_are_pinned_and_match_full_log_projection(self):
        manifest = json.loads((EVIDENCE / "manifest.json").read_text())
        self.assertEqual(len(manifest["jobs"]), 5)
        for job in manifest["jobs"]:
            with self.subTest(job=job["job_id"]):
                raw = (EVIDENCE / job["excerpt"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), job["excerpt_sha256"])
                observed = parse(raw, expected_sha=job["head_sha"], outcome=job["outcome"])
                expected = dict(job["projection"])
                for value in (observed, expected):
                    value.pop("decoded_log_normalized_sha256")
                self.assertEqual(observed, expected)
                self.assertEqual(len(raw.splitlines()), len(job["source_line_numbers"]))

    def test_later_pass_preserves_failure_and_unknown_cause(self):
        report = compare(self.failed, self.passed, expected_sha=SHA)
        self.assertEqual(report["failure"]["counts"]["NOT_RUN"], 10)
        self.assertEqual(report["success"]["counts"]["PASS"], 10)
        self.assertIsNone(report["failure"]["startup_elapsed_ms"])
        self.assertIsNone(report["failure"]["browser_session_version"])
        self.assertEqual(report["root_cause"], "ROOT_CAUSE_UNKNOWN")
        self.assertFalse(report["later_success_explains_failure"])

    def test_checkout_and_report_sha_must_both_match(self):
        self.reject(self.failed.replace(SHA.encode(), b"0" * 40, 1))
        self.reject(self.transform_report(lambda r: r.update(sha="0" * 40)))

    def test_duplicate_reports_are_ambiguous(self):
        line = next(line for line in self.failed.splitlines() if b"E6_BROWSER_EVIDENCE " in line)
        self.reject(self.failed + line + b"\n")

    def test_duplicate_json_keys_and_malformed_json_are_rejected(self):
        self.reject(self.failed.replace(b'"sha":', b'"sha":"bad","sha":'))
        self.reject(self.failed.replace(b"E6_BROWSER_EVIDENCE {", b"E6_BROWSER_EVIDENCE {invalid"))

    def test_case_results_and_counts_cannot_upgrade_a_failure(self):
        self.reject(self.transform_report(lambda r: r["tests"][0].update(result="PASS")))
        self.reject(self.transform_report(lambda r: r["counts"].update(NOT_RUN=9)))
        self.reject(self.transform_report(lambda r: r["counts"].update(FAIL=False)))
        self.reject(self.failed, outcome="success")

    def test_changed_blocker_or_missing_exit_evidence_is_not_the_same_failure(self):
        self.reject(self.failed.replace(b"Timed out: DevTools launch", b"WebSocket error"))
        self.reject(
            b"\n".join(line for line in self.failed.splitlines() if b"AssertionError:" not in line)
        )

    def test_report_outside_command_step_is_not_evidence(self):
        self.reject(
            self.failed.replace(
                b"E6_BROWSER_EVIDENCE ", b"##[group]Different step\nE6_BROWSER_EVIDENCE "
            )
        )

    def test_unknown_fields_and_private_diagnostics_are_not_exported(self):
        raw = self.transform_report(
            lambda r: r.update(
                private_url="https://private.invalid/?token=secret",
                stderr="secret-path",
                command="do not execute",
                root_cause="FIXED",
            )
        )
        report = parse(raw, expected_sha=SHA, outcome="failure")
        self.assertNotIn("secret", json.dumps(report))
        self.assertNotIn("private", json.dumps(report))
        self.assertEqual(report["root_cause"], "ROOT_CAUSE_UNKNOWN")

    def test_malformed_environment_and_product_are_fixed_errors(self):
        self.reject(self.transform_report(lambda r: r.update(environment=[])))
        self.reject(self.transform_report(lambda r: r["environment"].update(browser=[])))
        self.reject(
            self.transform_report(lambda r: r["browser"].update(product=[]), self.passed), "success"
        )

    def test_logs_are_bounded_and_utf8_only(self):
        self.reject(b"x" * (2 * 1024 * 1024 + 1))
        self.reject(b"\xff")

    def test_text_normalization_is_reproducible(self):
        first = parse(self.failed, expected_sha=SHA, outcome="failure")
        second = parse(
            b"\xef\xbb\xbf" + self.failed.replace(b"\n", b"\r\n") + b"\r\n",
            expected_sha=SHA,
            outcome="failure",
        )
        self.assertEqual(first, second)
