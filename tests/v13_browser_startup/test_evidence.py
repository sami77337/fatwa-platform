"""Evidence attribution and negative contracts; no product suites or CI reruns."""

import hashlib
import json
import unittest
from pathlib import Path

from .analyze_logs import MAX_LOG, EvidenceError, compare, parse

ROOT = Path(__file__).with_name("evidence")
SHA = "5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8"


class D6EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.failure = (ROOT / "134488475034.excerpt.log").read_bytes()
        self.success = (ROOT / "134490343087.excerpt.log").read_bytes()

    def test_real_excerpts_reproduce_observed_facts_without_inventing_causality(self):
        actual = compare(self.failure, self.success, expected_sha=SHA)
        saved = json.loads((ROOT / "comparison.json").read_text())
        for role in ("failure", "success"):
            # Full-log pins and excerpt pins are intentionally distinct.
            actual[role].pop("decoded_log_normalized_sha256")
            saved[role].pop("decoded_log_normalized_sha256")
        self.assertEqual(actual, saved)
        self.assertEqual(actual["root_cause"], "ROOT_CAUSE_UNKNOWN")
        self.assertTrue(actual["historical_failure_retained"])
        self.assertFalse(actual["same_region"])

    def test_excerpt_integrity_and_source_lines_are_pinned(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        comparison = json.loads((ROOT / "comparison.json").read_text())
        self.assertEqual(manifest["head_sha"], SHA)
        self.assertFalse(manifest["artifact_bytes_inspected"])
        for role, item in zip(("failure", "success"), manifest["jobs"], strict=True):
            raw = (ROOT / item["excerpt"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item["excerpt_sha256"])
            self.assertEqual(len(raw.splitlines()), len(item["source_line_numbers"]))
            self.assertEqual(item["source_line_numbers"], sorted(set(item["source_line_numbers"])))
            self.assertEqual(
                item["decoded_full_log_normalized_sha256"],
                comparison[role]["decoded_log_normalized_sha256"],
            )

    def test_wrong_head_missing_checkout_and_missing_step_are_rejected(self):
        for raw, sha in (
            (self.failure, "0" * 40),
            (self.failure.replace(b"git log -1 --format=%H", b"git log OMITTED"), SHA),
            (
                self.failure.replace(
                    b"##[group]Run python -B manage.py test tests.fast6_journey.test_browser",
                    b"other step",
                ),
                SHA,
            ),
        ):
            with self.subTest(sha=sha), self.assertRaises(EvidenceError):
                parse(raw, expected_sha=sha, outcome="failure")

    def test_failure_cannot_be_relabelled_or_timeout_relaxed(self):
        for old, new in (
            (b'"result":"NOT_RUN"', b'"result":"PASS"'),
            (b'"timeout_ms":30000', b'"timeout_ms":60000'),
            (b'"stage":"websocket"', b'"stage":"ready"'),
            (b'"elapsed_ms":30001', b'"elapsed_ms":true'),
            (b'"cleanup":{"result":"PASS"', b'"cleanup":{"result":"FAIL"'),
        ):
            with self.subTest(new=new), self.assertRaises(EvidenceError):
                parse(self.failure.replace(old, new), expected_sha=SHA, outcome="failure")

    def test_success_of_another_step_cannot_replace_failed_fast6(self):
        other = b'\n##[group]Run unrelated\n{"result":"PASS","catalog":"fixed synthetic test double; no database"}\n'
        result = compare(self.failure + other, self.success, expected_sha=SHA)
        self.assertEqual(result["failure"]["result"], "NOT_RUN")
        with self.assertRaises(EvidenceError):
            compare(self.success, self.failure, expected_sha=SHA)

    def test_duplicated_conflicting_report_or_json_keys_fail_closed(self):
        line = next(line for line in self.failure.splitlines() if b"AssertionError: 2 != 0" in line)
        with self.assertRaises(EvidenceError):
            parse(self.failure + line + b"\n", expected_sha=SHA, outcome="failure")
        with self.assertRaises(EvidenceError):
            parse(
                self.failure.replace(
                    b'"timeout_ms":30000', b'"timeout_ms":60000,"timeout_ms":30000'
                ),
                expected_sha=SHA,
                outcome="failure",
            )

    def test_untrusted_extra_report_text_is_not_exported(self):
        raw = self.failure.replace(
            b'"result":"NOT_RUN"',
            b'"result":"NOT_RUN","private":"secret http://example.invalid/?token=secret"',
        )
        output = json.dumps(compare(raw, self.success, expected_sha=SHA))
        self.assertNotIn("secret", output)
        self.assertNotIn("example.invalid", output)

    def test_invalid_encoding_size_and_report_shape_are_rejected(self):
        for raw in (
            b"\xff",
            b"x" * (MAX_LOG + 1),
            self.failure.replace(
                b'"startup":{"stage":"websocket","elapsed_ms":30001,"timeout_ms":30000}',
                b'"startup":null',
            ),
        ):
            with self.subTest(size=len(raw)), self.assertRaises(EvidenceError):
                parse(raw, expected_sha=SHA, outcome="failure")


if __name__ == "__main__":
    unittest.main()
