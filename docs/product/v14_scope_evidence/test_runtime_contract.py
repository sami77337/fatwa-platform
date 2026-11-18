"""Fabricated in-memory contract examples ONLY; never campaign execution receipts."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "v14_runtime_contract", Path(__file__).with_name("runtime_contract.py")
)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)

# Deliberately fake fixture identities: no file containing these is an evidence receipt.
HEAD = "1" * 40
REPORT = "2" * 40
CODE = b"def example():\n    pass\n"
REPORT_BYTES = ("PASS_BOUNDED SEC14-01B " + HEAD).encode()


def read_pinned(sha, path):
    return REPORT_BYTES if path == "docs/security/example.md" else CODE


def reference(path, symbol=None, sha=HEAD):
    return {
        "path": path,
        "symbol": symbol,
        "sha": sha,
        "file_sha256": contract.fingerprint(read_pinned(sha, path)),
    }


def fixture():
    """Positive structural fixture. It does not represent a real test run."""
    proof = {
        "tested_sha": HEAD,
        "sandbox": True,
        "browser": "FIXTURE_ONLY",
        "widths": [320, 1280],
        "external_requests": 0,
        "page_errors": 0,
        "canonical": {
            "cases": 1,
            "evaluation_revisions": 2,
            "evaluation_decisions": 1,
            "pdf_citations": 2,
            "pdf_confirmations": 2,
            "editorial_bindings": 1,
            "publications": 2,
            "publication_approvals": 2,
        },
        "recovery": {
            "state": "READY",
            "target_http": "PASS",
            "encrypted_only": True,
            "separate_key": True,
            "independent_target_postgres_server": True,
            "source_unchanged": True,
            "source_left_frozen": True,
            "partial_delivery_preserved": True,
            "wrong_key_and_hash_before_target": "DENIED",
            "ciphertext_sha256": "3" * 64,
            "pdf_plugin_selected_page": "NOT_VERIFIED",
        },
    }
    return {
        "state": "VERIFIED_BOUNDED",
        "product_sha": HEAD,
        "bounded_claim": "FIXTURE",
        "remaining": "FIXTURE",
        "status_upgrades": 0,
        "acceptance": "HOLD",
        "new_percentage": None,
        "credited_owner_points": [70],
        "code": [reference("apps/example.py")],
        "positive_tests": [reference("tests/example.py", "Example.test_positive")],
        "negative_tests": [reference("tests/example.py", "Example.test_negative")],
        "receipts": [
            {
                "tested_sha": HEAD,
                "postgres_major": major,
                "status": "completed",
                "conclusion": "success",
                "run_id": 1,
                "job_id": major,
                "url": f"{contract.REPO}/actions/runs/1/job/{major}",
                "attribution": "HOSTED_JOB_LOG_READ",
                "lines": [
                    "TESTED_SHA=" + HEAD,
                    f"SYNTHETIC_POSTGRES=postgres (PostgreSQL) {major}.1",
                    "test_positive (tests.example.Example.test_positive) ... ok",
                    "test_negative (tests.example.Example.test_negative) ... ok",
                    "V14_BROWSER_PROOF=" + json.dumps(proof),
                ],
            }
            for major in (17, 18)
        ],
        "security_review": {
            "verdict": "PASS_BOUNDED",
            "reviewed_sha": HEAD,
            "independent": True,
            "scope": "FIXTURE",
            "remaining": "FIXTURE",
            "report": reference("docs/security/example.md", sha=REPORT),
            "executions": [
                {
                    "postgres_major": major,
                    "tested_sha": HEAD,
                    "result": "PASS",
                    "passed": 1,
                    "original_reproducers_unchanged": True,
                    "attribution": "INDEPENDENT_REVIEWER_RECEIPT",
                }
                for major in (17, 18)
            ],
            "closed_blockers": ["SEC14-01B"],
            "preserved_blocked_heads": ["e5c504bb51157a67865ed2547d7fb67a38842117"],
        },
    }


class RuntimeContractTests(unittest.TestCase):
    def reject(self, mutate):
        value = copy.deepcopy(fixture())
        mutate(value)
        with self.assertRaises((AssertionError, KeyError)):
            contract.group(value, read_pinned=read_pinned)

    def alter_browser(self, value, mutate):
        for receipt in value["receipts"]:
            proof = json.loads(receipt["lines"][-1].split("=", 1)[1])
            mutate(proof)
            receipt["lines"][-1] = "V14_BROWSER_PROOF=" + json.dumps(proof)

    def test_structural_example_only(self):
        contract.group(fixture(), read_pinned=read_pinned)

    def test_wrong_head_receipt_denied(self):
        self.reject(lambda v: v["receipts"][0].update(tested_sha=REPORT))

    def test_missing_or_duplicate_major_denied(self):
        self.reject(lambda v: v["receipts"].pop())
        self.reject(lambda v: v["receipts"][1].update(postgres_major=17))

    def test_positive_without_negative_execution_denied(self):
        self.reject(lambda v: v["receipts"][0]["lines"].pop(3))

    def test_same_method_wrong_class_denied(self):
        self.reject(
            lambda v: v["receipts"][0]["lines"].__setitem__(
                3, "test_negative (tests.example.Other.test_negative) ... ok"
            )
        )

    def test_file_hash_mismatch_denied(self):
        self.reject(lambda v: v["code"][0].update(file_sha256="0" * 64))

    def test_pending_or_other_head_security_denied(self):
        self.reject(lambda v: v["security_review"].update(verdict="PENDING"))
        self.reject(lambda v: v["security_review"].update(reviewed_sha=REPORT))

    def test_removed_blocked_history_denied(self):
        self.reject(lambda v: v["security_review"].update(preserved_blocked_heads=[]))

    def test_unsandboxed_or_missing_browser_denied(self):
        self.reject(lambda v: self.alter_browser(v, lambda p: p.update(sandbox=False)))
        self.reject(lambda v: v["receipts"][0]["lines"].pop())

    def test_inherited_v13_subset_denied(self):
        self.reject(lambda v: self.alter_browser(v, lambda p: p["canonical"].pop("pdf_citations")))
        self.reject(
            lambda v: self.alter_browser(v, lambda p: p["canonical"].update(editorial_bindings=0))
        )

    def test_original_server_or_unencrypted_restore_denied(self):
        for key in ("encrypted_only", "independent_target_postgres_server", "source_left_frozen"):
            with self.subTest(key=key):
                self.reject(
                    lambda v: self.alter_browser(v, lambda p: p["recovery"].update({key: False}))
                )

    def test_runtime_credit_cannot_upgrade_status_or_percentage(self):
        self.reject(lambda v: v.update(status_upgrades=1))
        self.reject(lambda v: v.update(new_percentage=84))

    def test_skipped_negative_test_not_pass(self):
        self.reject(
            lambda v: v["receipts"][0]["lines"].__setitem__(
                3, "test_negative (tests.example.Example.test_negative) ... skipped"
            )
        )

    def test_actual_major_required_in_log(self):
        self.reject(
            lambda v: v["receipts"][1]["lines"].__setitem__(
                1, "SYNTHETIC_POSTGRES=postgres (PostgreSQL) 17.1"
            )
        )


if __name__ == "__main__":
    unittest.main()
