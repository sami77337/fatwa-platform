"""Small synthetic fixtures only; no reconstruction of 70/58 source records."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contracts.validator import (
    EXPECTED_COUNTS,
    MAX_BYTES,
    MAX_ISSUES,
    SCHEMA_PATH,
    inspect_structure,
    validate_inventory,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIXTURE = HERE / "fixtures" / "synthetic_inventory.json"
ORIGINAL = HERE / "fixtures" / "synthetic_review_excerpt.json"
FIXTURE_SHA = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


def codes(issues: list[dict[str, str]]) -> set[str]:
    return {issue["code"] for issue in issues}


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def assert_rejected(self, code: str) -> None:
        self.assertIn(code, codes(inspect_structure(self.document, synthetic=True)))

    def test_small_synthetic_inventory_valid(self) -> None:
        self.assertEqual(inspect_structure(self.document, synthetic=True), [])
        self.assertEqual(len(self.document["actions"]), 4)
        self.assertEqual(len(self.document["transitions"]), 1)

    def test_synthetic_cannot_validate_source_mode(self) -> None:
        found = codes(inspect_structure(self.document))
        self.assertIn("FIXTURE_MODE_MISMATCH", found)
        self.assertIn("INVENTORY_COUNT_MISMATCH", found)

    def test_relabeling_fixture_still_fails_source_counts(self) -> None:
        self.document["fixture_kind"] = "SOURCE_INVENTORY"
        self.assert_rejected_source("INVENTORY_COUNT_MISMATCH")

    def assert_rejected_source(self, code: str) -> None:
        self.assertIn(code, codes(inspect_structure(self.document)))

    def test_admin_roles_are_peers(self) -> None:
        self.document["policy"]["role_hierarchy"]["ORGANIZER_ADMIN"] = "ABOVE_MUFTI"
        self.assert_rejected("ROLE_ESCALATION")

    def test_organizer_cannot_be_escalated(self) -> None:
        self.document["policy"]["role_hierarchy"]["ORGANIZER"] = "ADMIN_PEER"
        self.assert_rejected("ROLE_ESCALATION")

    def test_scholarly_authority_cannot_expand(self) -> None:
        self.document["policy"]["scholarly_authorities"].append("ORGANIZER_ADMIN")
        self.assert_rejected("ROLE_ESCALATION")

    def test_only_mufti_candidate_for_creation_and_approval(self) -> None:
        for operation in ("SCHOLARLY_CREATE", "SCHOLARLY_APPROVE"):
            for role in ("ORGANIZER_ADMIN", "ORGANIZER"):
                with self.subTest(operation=operation, role=role):
                    self.document["actions"][2]["operation"] = operation
                    self.document["actions"][2]["candidate_principals"][0]["name"] = role
                    self.assert_rejected("ROLE_ESCALATION")

    def test_transition_cannot_expand_action_candidates(self) -> None:
        self.document["transitions"][0]["candidate_principals"].append(
            {"kind": "ROLE", "name": "ORGANIZER_ADMIN"}
        )
        self.assert_rejected("ROLE_ESCALATION")

    def test_wildcard_principal_forbidden(self) -> None:
        self.document["actions"][2]["candidate_principals"][0]["name"] = "*"
        self.assert_rejected("ROLE_ESCALATION")

    def test_shadow_grant_in_action_and_transition(self) -> None:
        for category in ("actions", "transitions"):
            with self.subTest(category=category):
                document = copy.deepcopy(self.document)
                document[category][0]["grant_effect"] = "ALLOW"
                self.assertIn("SHADOW_GRANT", codes(inspect_structure(document, synthetic=True)))

    def test_undeclared_shadow_fields_forbidden(self) -> None:
        for key in ("permissions", "grants", "is_superuser", "dispatch", "role_inheritance"):
            with self.subTest(key=key):
                document = copy.deepcopy(self.document)
                document["actions"][2][key] = True
                self.assertIn("SHADOW_GRANT", codes(inspect_structure(document, synthetic=True)))

    def test_unknown_fields_fail_closed_at_every_level(self) -> None:
        for target in (self.document, self.document["policy"],
                       self.document["actions"][0], self.document["actions"][0]["source_ref"],
                       self.document["transitions"][0]["candidate_principals"][0]):
            with self.subTest(target_keys=list(target)):
                target["unknown_extension"] = "not accepted"
                self.assert_rejected("UNKNOWN_FIELD")
                del target["unknown_extension"]

    def test_grant_binding_cannot_activate(self) -> None:
        self.document["actions"][2]["binding"] = "ACTIVE"
        self.assert_rejected("SHADOW_GRANT")

    def test_deny_default_cannot_change(self) -> None:
        self.document["actions"][2]["deny_default"] = "ALLOW_DEFAULT"
        self.assert_rejected("GRANT_NOT_DENIED")

    def test_service_identity_cannot_impersonate_role(self) -> None:
        self.document["actions"][2]["candidate_principals"][0]["kind"] = "SERVICE"
        self.assert_rejected("SERVICE_IDENTITY_IMPERSONATION")

    def test_domain_transaction_is_never_a_principal(self) -> None:
        self.document["actions"][2]["candidate_principals"][0]["kind"] = "DOMAIN_TRANSACTION"
        self.assert_rejected("SERVICE_IDENTITY_IMPERSONATION")

    def test_known_internal_effect_cannot_be_relabelled_action(self) -> None:
        self.document["actions"][0]["record_kind"] = "ACTION"
        self.assert_rejected("SERVICE_IDENTITY_IMPERSONATION")

    def test_internal_effect_has_no_candidate_principals(self) -> None:
        self.document["actions"][0]["candidate_principals"] = [{"kind": "ROLE", "name": "MUFTI"}]
        self.assert_rejected("SERVICE_IDENTITY_IMPERSONATION")

    def test_internal_effect_requires_parent_transaction(self) -> None:
        self.document["actions"][0]["parent_transaction"] = None
        self.assert_rejected("SERVICE_IDENTITY_IMPERSONATION")

    def test_regular_action_cannot_be_internal_effect(self) -> None:
        self.document["actions"][2]["operation"] = "INTERNAL_ATOMIC_EFFECT"
        self.assert_rejected("SERVICE_IDENTITY_IMPERSONATION")

    def test_parent_effect_cannot_be_callable(self) -> None:
        for index in (0, 1):
            with self.subTest(effect=index):
                self.document["actions"][index]["callable"] = True
                self.assert_rejected("PARENT_EFFECT_CALLABLE")

    def test_parent_effect_cannot_be_transition_target(self) -> None:
        self.document["transitions"][0]["action_id"] = "P00-03::case.project"
        self.assert_rejected("PARENT_EFFECT_CALLABLE")

    def test_regular_action_cannot_be_callable(self) -> None:
        self.document["actions"][2]["callable"] = True
        self.assert_rejected("ACTIVE_EXECUTION_FORBIDDEN")

    def test_transition_cannot_be_enabled(self) -> None:
        self.document["transitions"][0]["enabled"] = True
        self.assert_rejected("ACTIVE_EXECUTION_FORBIDDEN")

    def test_stale_policy_token_at_all_locations(self) -> None:
        for target in (self.document["policy"], self.document["actions"][0], self.document["transitions"][0]):
            with self.subTest(target_keys=list(target)):
                original = target["policy_token"]
                target["policy_token"] = "obsolete-policy"
                self.assert_rejected("STALE_POLICY_TOKEN")
                target["policy_token"] = original

    def test_historical_answers_immutable(self) -> None:
        for category in ("actions", "transitions"):
            with self.subTest(category=category):
                document = copy.deepcopy(self.document)
                document[category][0]["historical_answer_mutable"] = True
                self.assertIn("MUTABLE_HISTORICAL_ANSWER", codes(inspect_structure(document, synthetic=True)))

    def test_boolean_not_interchangeable_with_zero(self) -> None:
        self.document["actions"][0]["historical_answer_mutable"] = 0
        self.assert_rejected("MUTABLE_HISTORICAL_ANSWER")

    def test_owner_approval_cannot_be_self_asserted(self) -> None:
        self.document["policy"]["owner_approval"] = "APPROVED"
        self.assert_rejected("POLICY_ACTIVATION_FORBIDDEN")

    def test_gates_cannot_be_advanced(self) -> None:
        for key in ("gate_b", "gates_c_d_e", "phase01"):
            with self.subTest(key=key):
                original = self.document["policy"][key]
                self.document["policy"][key] = "PASSED"
                self.assert_rejected("GATE_ACTIVATION_FORBIDDEN")
                self.document["policy"][key] = original

    def test_ai_cannot_be_activated(self) -> None:
        self.document["policy"]["ai_mode"] = "ENABLED"
        self.assert_rejected("AI_ACTIVATION_FORBIDDEN")

    def test_duplicate_action_and_transition_ids(self) -> None:
        for category in ("actions", "transitions"):
            with self.subTest(category=category):
                document = copy.deepcopy(self.document)
                document[category].append(copy.deepcopy(document[category][0]))
                self.assertIn("DUPLICATE_RECORD_ID", codes(inspect_structure(document, synthetic=True)))

    def test_duplicate_source_ids(self) -> None:
        self.document["source_documents"].append(copy.deepcopy(self.document["source_documents"][0]))
        self.assert_rejected("DUPLICATE_SOURCE_ID")

    def test_duplicate_original_record_references(self) -> None:
        self.document["actions"][3]["source_ref"] = copy.deepcopy(self.document["actions"][2]["source_ref"])
        self.assert_rejected("DUPLICATE_SOURCE_RECORD")

    def test_unknown_source_reference(self) -> None:
        self.document["actions"][2]["source_ref"]["document_id"] = "undeclared-source"
        self.assert_rejected("UNKNOWN_SOURCE_REFERENCE")

    def test_unknown_action_reference(self) -> None:
        self.document["transitions"][0]["action_id"] = "missing-action"
        self.assert_rejected("UNKNOWN_ACTION_REFERENCE")

    def test_duplicate_candidate_roles(self) -> None:
        self.document["actions"][2]["candidate_principals"].append(
            copy.deepcopy(self.document["actions"][2]["candidate_principals"][0])
        )
        self.assert_rejected("SCHEMA_VIOLATION")

    def test_malformed_shapes_fail_closed(self) -> None:
        for value in (None, [], "invalid", {"actions": []}):
            with self.subTest(value=value):
                self.assertTrue(inspect_structure(value, synthetic=True))

    def test_expected_counts_are_requirements_not_invented_records(self) -> None:
        self.assertEqual(EXPECTED_COUNTS, {"actions": 70, "DOMAIN_STATE": 37,
                         "UI": 33, "UNMAPPED_HOLD": 55, "MAPPED_DRAFT": 15, "transitions": 58})
        self.assertLess(len(self.document["actions"]), EXPECTED_COUNTS["actions"])

    def test_schema_uses_only_supported_closed_keywords(self) -> None:
        supported = {"$schema", "$id", "title", "type", "properties", "required",
                     "additionalProperties", "const", "enum", "x-error-code", "items",
                     "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern"}

        def inspect(rule: dict) -> None:
            self.assertTrue(set(rule).issubset(supported))
            if rule.get("type") == "object":
                self.assertIs(rule["additionalProperties"], False)
                self.assertEqual(set(rule["required"]), set(rule["properties"]))
            for child in rule.get("properties", {}).values():
                inspect(child)
            if "items" in rule:
                inspect(rule["items"])

        inspect(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


class FileAndCLITests(unittest.TestCase):
    def setUp(self) -> None:
        runtime = HERE / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def write(self, data: bytes) -> Path:
        path = self.directory / "inventory.json"
        path.write_bytes(data)
        return path

    def synthetic_report(self, path: Path = FIXTURE, **kwargs) -> dict:
        return validate_inventory(path, source_paths={"synthetic-review": ORIGINAL}, synthetic=True, **kwargs)

    def test_missing_inventory_is_blocked(self) -> None:
        for path in (None, self.directory / "absent.json"):
            with self.subTest(path=path):
                report = validate_inventory(path)
                self.assertEqual(report["status"], "BLOCKED")
                self.assertIn("SOURCE_CONTRACT_MISSING", codes(report["issues"]))
                self.assertFalse(report["validation_passed"])

    def test_synthetic_success_still_has_zero_grants_and_pending_gates(self) -> None:
        report = self.synthetic_report(expected_sha256=FIXTURE_SHA)
        self.assertEqual(report["status"], "SYNTHETIC_VALIDATED")
        self.assertTrue(report["validation_passed"])
        self.assertFalse(report["runtime_executable"])
        self.assertEqual(report["active_grants"], 0)
        self.assertEqual(report["grant_effect"], "NONE")
        self.assertEqual(report["owner_approval"], "OWNER_APPROVAL_PENDING")
        self.assertEqual(report["gate_b"], "NOT_PASSED")
        self.assertEqual(report["gates_c_d_e"], "HOLD")
        self.assertEqual(report["phase01"], "BLOCKED")
        self.assertTrue(report["inventory_identity"]["hash_verified"])
        self.assertTrue(report["original_sources"][0]["hash_verified"])

    def test_source_requires_inventory_pin(self) -> None:
        report = validate_inventory(FIXTURE, source_paths={"synthetic-review": ORIGINAL})
        self.assertIn("SOURCE_HASH_REQUIRED", codes(report["issues"]))
        self.assertEqual(report["status"], "BLOCKED")

    def test_bad_inventory_hash(self) -> None:
        report = self.synthetic_report(expected_sha256="0" * 64)
        self.assertIn("SOURCE_HASH_MISMATCH", codes(report["issues"]))
        self.assertFalse(report["validation_passed"])

    def test_malformed_inventory_pin(self) -> None:
        report = self.synthetic_report(expected_sha256="not-a-hash")
        self.assertIn("INVALID_SOURCE_HASH", codes(report["issues"]))

    def test_missing_original_source(self) -> None:
        report = validate_inventory(FIXTURE, synthetic=True)
        self.assertIn("SOURCE_CONTRACT_MISSING", codes(report["issues"]))
        self.assertEqual(report["status"], "BLOCKED")

    def test_missing_original_source_path(self) -> None:
        report = validate_inventory(FIXTURE, synthetic=True,
                                    source_paths={"synthetic-review": self.directory / "missing.json"})
        self.assertIn("SOURCE_CONTRACT_MISSING", codes(report["issues"]))

    def test_original_hash_mismatch(self) -> None:
        path = self.write(b"different original bytes")
        report = validate_inventory(FIXTURE, synthetic=True, source_paths={"synthetic-review": path})
        self.assertIn("SOURCE_HASH_MISMATCH", codes(report["issues"]))
        self.assertFalse(report["original_sources"][0]["hash_verified"])

    def test_extra_source_path_rejected(self) -> None:
        report = validate_inventory(FIXTURE, synthetic=True,
                                    source_paths={"synthetic-review": ORIGINAL, "extra": ORIGINAL})
        self.assertIn("SOURCE_SET_MISMATCH", codes(report["issues"]))

    def test_malformed_json_does_not_echo_input(self) -> None:
        private_marker = "PRIVATE_TEST_MARKER_NEVER_ECHO"
        path = self.write(("{" + private_marker).encode("utf-8"))
        report = self.synthetic_report(path)
        self.assertIn("INVALID_JSON", codes(report["issues"]))
        self.assertNotIn(private_marker, json.dumps(report))

    def test_duplicate_json_keys_rejected(self) -> None:
        path = self.write(b'{"schema_version":"1.0","schema_version":"1.0"}')
        self.assertIn("DUPLICATE_JSON_KEY", codes(self.synthetic_report(path)["issues"]))

    def test_nonstandard_json_number_rejected(self) -> None:
        for value in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(value=value):
                path = self.write(value)
                self.assertIn("NONSTANDARD_JSON_NUMBER", codes(self.synthetic_report(path)["issues"]))

    def test_invalid_utf8_rejected(self) -> None:
        path = self.write(b"\xff\xfe")
        self.assertIn("INVALID_JSON", codes(self.synthetic_report(path)["issues"]))

    def test_oversized_inventory_rejected(self) -> None:
        path = self.write(b" " * (MAX_BYTES + 1))
        self.assertIn("INPUT_TOO_LARGE", codes(self.synthetic_report(path)["issues"]))

    def test_extreme_integer_rejected_without_crash(self) -> None:
        path = self.write(b"9" * 10000)
        self.assertIn("INVALID_JSON", codes(self.synthetic_report(path)["issues"]))

    def test_excess_diagnostics_are_bounded(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for index in range(MAX_ISSUES * 3):
            document[f"unknown_{index:04}"] = True
        path = self.write(json.dumps(document).encode("utf-8"))
        report = self.synthetic_report(path)
        self.assertLessEqual(len(report["issues"]), MAX_ISSUES + 1)
        self.assertIn("ISSUE_LIMIT_REACHED", codes(report["issues"]))
        self.assertEqual(report, self.synthetic_report(path))

    def test_oversized_original_rejected(self) -> None:
        path = self.write(b" " * (MAX_BYTES + 1))
        report = validate_inventory(FIXTURE, synthetic=True, source_paths={"synthetic-review": path})
        self.assertIn("INPUT_TOO_LARGE", codes(report["issues"]))

    def test_unreadable_inventory_is_blocked(self) -> None:
        report = validate_inventory(self.directory)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("SOURCE_UNREADABLE", codes(report["issues"]))

    def test_deeply_nested_json_rejected(self) -> None:
        path = self.write(b"[" * 2000 + b"0" + b"]" * 2000)
        self.assertIn("INVALID_JSON", codes(self.synthetic_report(path)["issues"]))

    def test_inventory_cannot_supply_a_source_path(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        document["source_documents"][0]["path"] = str(ORIGINAL)
        path = self.write(json.dumps(document).encode("utf-8"))
        report = validate_inventory(path, synthetic=True)
        self.assertIn("UNKNOWN_FIELD", codes(report["issues"]))
        self.assertEqual(report["original_sources"], [])

    def test_reports_are_deterministic(self) -> None:
        self.assertEqual(self.synthetic_report(), self.synthetic_report())

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-m", "contracts", *args], cwd=REPO,
                              capture_output=True, text=True, check=False)

    def test_cli_default_missing_source_json_exit_two(self) -> None:
        result = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertIn("SOURCE_CONTRACT_MISSING", codes(report["issues"]))
        self.assertFalse(report["runtime_executable"])

    def test_cli_explicit_synthetic_success_exit_zero(self) -> None:
        result = self.cli(str(FIXTURE), "--synthetic-fixture", "--sha256", FIXTURE_SHA,
                          "--source", "synthetic-review=" + str(ORIGINAL))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "SYNTHETIC_VALIDATED")

    def test_cli_rejects_duplicate_and_malformed_source_arguments(self) -> None:
        for args in (("--source", "invalid"), ("--source", "id="),
                     ("--source", "id=one", "--source", "id=two")):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("INVALID_SOURCE_ARGUMENT", codes(json.loads(result.stdout)["issues"]))

    def test_cli_does_not_report_a_source_acceptance_for_fixture(self) -> None:
        result = self.cli(str(FIXTURE), "--sha256", FIXTURE_SHA,
                          "--source", "synthetic-review=" + str(ORIGINAL))
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertIn("FIXTURE_MODE_MISMATCH", codes(report["issues"]))
        self.assertIn("INVENTORY_COUNT_MISMATCH", codes(report["issues"]))


if __name__ == "__main__":
    unittest.main()
