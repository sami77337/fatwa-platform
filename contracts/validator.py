"""Standard-library, offline validation of inert documentation inventories.

Successful validation never authorizes an operation or accepts an owner policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

SCHEMA_PATH = Path(__file__).with_name("inventory.schema.json")
MAX_BYTES = 4 * 1024 * 1024
MAX_ISSUES = 100
POLICY_TOKEN = "D-067:D-068:U03-U10:OWNER_APPROVAL_PENDING:20261013"
EXPECTED_COUNTS = {
    "actions": 70,
    "DOMAIN_STATE": 37,
    "UI": 33,
    "UNMAPPED_HOLD": 55,
    "MAPPED_DRAFT": 15,
    "transitions": 58,
}
INTERNAL_EFFECTS = {"P00-03::case.project", "P00-03::delivery.hold"}
SCHOLARLY_OPERATIONS = {"SCHOLARLY_CREATE", "SCHOLARLY_APPROVE"}
SHADOW_FIELDS = {
    "allow", "allowed", "grants", "permissions", "is_superuser",
    "role_inheritance", "active_grants", "runtime_executable", "dispatch",
}


class InvalidJSON(ValueError):
    """Ambiguous or non-standard JSON is not an inventory."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidJSON("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise InvalidJSON("NONSTANDARD_JSON_NUMBER")


def _issue(issues: list[dict[str, str]], code: str, path: str,
           message: str, *, blocker: bool = False) -> None:
    # Never echo field values, file contents, or parser excerpts into a report.
    if len(issues) >= MAX_ISSUES:
        if len(issues) == MAX_ISSUES:
            issues.append({"code": "ISSUE_LIMIT_REACHED", "path": "$",
                           "message": "Further invalid input diagnostics were suppressed.",
                           "severity": "ERROR"})
        return
    issues.append({"code": code, "path": path, "message": message,
                   "severity": "BLOCKER" if blocker else "ERROR"})


def _is_type(value: Any, kind: str) -> bool:
    if kind == "object":
        return type(value) is dict
    if kind == "array":
        return type(value) is list
    if kind == "string":
        return type(value) is str
    if kind == "boolean":
        return type(value) is bool
    if kind == "null":
        return value is None
    raise ValueError("Unsupported schema type")


def _same_json(left: Any, right: Any) -> bool:
    # Python considers False == 0; JSON Schema does not.
    return json.dumps(left, sort_keys=True, ensure_ascii=True) == json.dumps(
        right, sort_keys=True, ensure_ascii=True
    )


def _schema_errors(value: Any, rule: dict[str, Any], path: str,
                   issues: list[dict[str, str]]) -> None:
    """Evaluate only the documented subset used by the bundled schema.

    No reference resolution, imports, callbacks, or network requests occur.
    Schema keywords outside this subset are checked by the schema tests.
    """
    if len(issues) > MAX_ISSUES:
        return
    code = rule.get("x-error-code", "SCHEMA_VIOLATION")
    kinds = rule.get("type")
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(_is_type(value, kind) for kind in kinds):
            _issue(issues, code, path, "Incorrect JSON type.")
            return
    if "const" in rule and not _same_json(value, rule["const"]):
        _issue(issues, code, path, "Value violates a locked documentation invariant.")
    if "enum" in rule and not any(_same_json(value, item) for item in rule["enum"]):
        _issue(issues, code, path, "Value is outside the explicit allowed set.")
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", MAX_BYTES):
            _issue(issues, code, path, "String length is outside the schema limits.")
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            _issue(issues, code, path, "String does not match the required format.")
    if isinstance(value, dict):
        properties = rule.get("properties", {})
        for name in rule.get("required", []):
            if name not in value:
                _issue(issues, code, path, "A required field is absent.")
        if rule.get("additionalProperties") is False:
            for name in sorted(value.keys() - properties.keys()):
                extra_code = "SHADOW_GRANT" if name in SHADOW_FIELDS else "UNKNOWN_FIELD"
                _issue(issues, extra_code, path, "An undeclared field is forbidden.")
                if len(issues) > MAX_ISSUES:
                    return
        for name in sorted(value.keys() & properties.keys()):
            _schema_errors(value[name], properties[name], path + "." + name, issues)
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", MAX_BYTES):
            _issue(issues, code, path, "Array length is outside the schema limits.")
            return
        if rule.get("uniqueItems"):
            keys = [json.dumps(item, sort_keys=True, ensure_ascii=True) for item in value]
            if len(set(keys)) != len(keys):
                _issue(issues, code, path, "Duplicate array entries are forbidden.")
        if "items" in rule:
            for index, item in enumerate(value):
                _schema_errors(item, rule["items"], f"{path}[{index}]", issues)


def _counts(document: Any) -> dict[str, int]:
    actions = document.get("actions", []) if isinstance(document, dict) else []
    transitions = document.get("transitions", []) if isinstance(document, dict) else []
    actions = actions if isinstance(actions, list) else []
    transitions = transitions if isinstance(transitions, list) else []
    rows = Counter(row.get("row_type") for row in actions
                   if isinstance(row, dict) and isinstance(row.get("row_type"), str))
    mappings = Counter(row.get("mapping_status") for row in actions
                       if isinstance(row, dict) and isinstance(row.get("mapping_status"), str))
    return {"actions": len(actions), "DOMAIN_STATE": rows["DOMAIN_STATE"],
            "UI": rows["UI"], "UNMAPPED_HOLD": mappings["UNMAPPED_HOLD"],
            "MAPPED_DRAFT": mappings["MAPPED_DRAFT"], "transitions": len(transitions)}


def inspect_structure(document: Any, *, synthetic: bool = False) -> list[dict[str, str]]:
    """Inspect structure and invariants without treating records as executable."""
    issues: list[dict[str, str]] = []
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _schema_errors(document, schema, "$", issues)
    if issues:
        return sorted(issues, key=lambda item: (item["path"], item["code"]))
    required_kind = "SYNTHETIC" if synthetic else "SOURCE_INVENTORY"
    if document["fixture_kind"] != required_kind:
        _issue(issues, "FIXTURE_MODE_MISMATCH", "$.fixture_kind",
               "Fixture identity does not match the explicit validation mode.")
    if not synthetic and _counts(document) != EXPECTED_COUNTS:
        _issue(issues, "INVENTORY_COUNT_MISMATCH", "$",
               "Source inventory must contain exactly 70 actions (37/33, 55/15) and 58 transitions.")

    documents = {item["document_id"] for item in document["source_documents"]}
    if len(documents) != len(document["source_documents"]):
        _issue(issues, "DUPLICATE_SOURCE_ID", "$.source_documents", "Source IDs must be unique.")
    actions: dict[str, dict[str, Any]] = {}
    source_records: set[tuple[str, str]] = set()
    for category in ("actions", "transitions"):
        seen_ids: set[str] = set()
        id_field = "action_id" if category == "actions" else "transition_id"
        for index, row in enumerate(document[category]):
            path = f"$.{category}[{index}]"
            if row[id_field] in seen_ids:
                _issue(issues, "DUPLICATE_RECORD_ID", path, "Inventory IDs must be unique.")
            seen_ids.add(row[id_field])
            ref = row["source_ref"]
            if ref["document_id"] not in documents:
                _issue(issues, "UNKNOWN_SOURCE_REFERENCE", path + ".source_ref",
                       "Record refers to an undeclared source document.")
            source_key = (ref["document_id"], ref["record_id"])
            if source_key in source_records:
                _issue(issues, "DUPLICATE_SOURCE_RECORD", path + ".source_ref",
                       "An original record reference cannot count as two inventory records.")
            source_records.add(source_key)
            if category == "actions":
                actions[row["action_id"]] = row
                internal = row["record_kind"] == "INTERNAL_ATOMIC_EFFECT"
                expected_internal = row["action_id"] in INTERNAL_EFFECTS
                if internal != expected_internal or (internal and (
                    row["operation"] != "INTERNAL_ATOMIC_EFFECT"
                    or row["row_type"] != "DOMAIN_STATE"
                    or row["parent_transaction"] != "P00-03"
                    or row["candidate_principals"]
                )) or (not internal and (
                    row["operation"] == "INTERNAL_ATOMIC_EFFECT"
                    or row["parent_transaction"] is not None
                )):
                    _issue(issues, "SERVICE_IDENTITY_IMPERSONATION", path,
                           "Internal atomic effects are not runnable principals or role-bound actions.")
                if row["callable"]:
                    _issue(issues, "PARENT_EFFECT_CALLABLE" if internal or expected_internal
                           else "ACTIVE_EXECUTION_FORBIDDEN", path + ".callable",
                           "Contract rows cannot be called or dispatched.")
                if row["operation"] in SCHOLARLY_OPERATIONS and any(
                    principal["name"] != "MUFTI" for principal in row["candidate_principals"]
                ):
                    _issue(issues, "ROLE_ESCALATION", path + ".candidate_principals",
                           "Only MUFTI may be a candidate for scholarly creation or approval.")
            elif row["enabled"]:
                _issue(issues, "ACTIVE_EXECUTION_FORBIDDEN", path + ".enabled",
                       "Draft transitions cannot be enabled.")
    if not synthetic and not INTERNAL_EFFECTS.issubset(actions):
        _issue(issues, "INTERNAL_EFFECT_MISSING", "$.actions",
               "Both known P00-03 internal effects must be documented as inert effects.")
    for index, transition in enumerate(document["transitions"]):
        path = f"$.transitions[{index}]"
        action = actions.get(transition["action_id"])
        if action is None:
            _issue(issues, "UNKNOWN_ACTION_REFERENCE", path + ".action_id",
                   "Transition refers to an absent action.")
            continue
        if action["record_kind"] == "INTERNAL_ATOMIC_EFFECT":
            _issue(issues, "PARENT_EFFECT_CALLABLE", path + ".action_id",
                   "Internal parent-transaction effects cannot be workflow dispatch targets.")
        action_roles = {item["name"] for item in action["candidate_principals"]}
        transition_roles = {item["name"] for item in transition["candidate_principals"]}
        if not transition_roles.issubset(action_roles):
            _issue(issues, "ROLE_ESCALATION", path + ".candidate_principals",
                   "Transition candidates cannot exceed the referenced action candidates.")
    return sorted(issues, key=lambda item: (item["path"], item["code"]))


def _read_bytes(path: Path) -> bytes:
    # Bounded reads protect reports from oversized or concurrently growing files.
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise InvalidJSON("INPUT_TOO_LARGE")
    return data


def _base_report(synthetic: bool) -> dict[str, Any]:
    return {
        "report_version": "1.0", "status": "BLOCKED", "validation_passed": False,
        "mode": "SYNTHETIC" if synthetic else "SOURCE_INVENTORY",
        "runtime_executable": False, "active_grants": 0, "grant_effect": "NONE",
        "owner_approval": "OWNER_APPROVAL_PENDING", "gate_b": "NOT_PASSED",
        "gates_c_d_e": "HOLD", "phase01": "BLOCKED",
        "validation_scope": "STRUCTURE_POLICY_HASHES_ONLY",
        "source_acceptance_passed": False, "policy_approval_verified": False,
        "record_content_binding": "NOT_VERIFIED_REQUIRES_REVIEWED_SOURCE_ADAPTER",
        "expected_source_counts": EXPECTED_COUNTS.copy(), "inventory_counts": None,
        "inventory_identity": None, "original_sources": [], "issues": [],
    }


def _finish(report: dict[str, Any]) -> dict[str, Any]:
    issues = report["issues"]
    report["issues"] = sorted(issues, key=lambda item: (item["path"], item["code"]))
    if issues:
        report["status"] = "BLOCKED" if any(
            issue["severity"] == "BLOCKER" for issue in issues
        ) else "INVALID"
    else:
        report["validation_passed"] = True
        report["status"] = "SYNTHETIC_VALIDATED" if report["mode"] == "SYNTHETIC" else "DOCUMENTATION_VALIDATED"
    return report


def validate_inventory(path: Path | str | None = None, *,
                       expected_sha256: str | None = None,
                       source_paths: Mapping[str, Path | str] | None = None,
                       synthetic: bool = False) -> dict[str, Any]:
    """Hash and inspect supplied local files; never resolve paths from inventory data."""
    report = _base_report(synthetic)
    issues = report["issues"]
    if path is None:
        _issue(issues, "SOURCE_CONTRACT_MISSING", "$",
               "No reviewed source contract inventory was supplied.", blocker=True)
        return _finish(report)
    try:
        inventory_bytes = _read_bytes(Path(path))
    except FileNotFoundError:
        _issue(issues, "SOURCE_CONTRACT_MISSING", "$",
               "The supplied inventory file is missing.", blocker=True)
        return _finish(report)
    except InvalidJSON as error:
        _issue(issues, str(error), "$", "Inventory exceeds the offline input limit.")
        return _finish(report)
    except OSError:
        _issue(issues, "SOURCE_UNREADABLE", "$", "Inventory file could not be read.", blocker=True)
        return _finish(report)
    digest = hashlib.sha256(inventory_bytes).hexdigest()
    valid_pin = isinstance(expected_sha256, str) and re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is not None
    report["inventory_identity"] = {
        "sha256": digest, "expected_sha256": expected_sha256 if valid_pin else None,
        "hash_verified": valid_pin and digest == expected_sha256,
    }
    if expected_sha256 is not None and not valid_pin:
        _issue(issues, "INVALID_SOURCE_HASH", "$", "Inventory pin must be a lowercase SHA256 digest.")
    elif valid_pin and digest != expected_sha256:
        _issue(issues, "SOURCE_HASH_MISMATCH", "$", "Inventory bytes do not match the supplied pin.")
    elif not synthetic and not valid_pin:
        _issue(issues, "SOURCE_HASH_REQUIRED", "$", "Source mode requires an independently supplied inventory hash.", blocker=True)
    try:
        document = json.loads(inventory_bytes.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
    except InvalidJSON as error:
        _issue(issues, str(error), "$", "Ambiguous or non-standard JSON is forbidden.")
        return _finish(report)
    except (UnicodeError, ValueError, RecursionError):
        _issue(issues, "INVALID_JSON", "$", "Inventory must be bounded, strict UTF-8 JSON.")
        return _finish(report)
    report["inventory_counts"] = _counts(document)
    structure_issues = inspect_structure(document, synthetic=synthetic)
    for issue in structure_issues:
        _issue(issues, issue["code"], issue["path"], issue["message"],
               blocker=issue["severity"] == "BLOCKER")
    # Only schema-conforming source references can select a caller-supplied path.
    schema_issues: list[dict[str, str]] = []
    _schema_errors(document, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")), "$", schema_issues)
    if schema_issues:
        return _finish(report)
    paths = dict(source_paths or {})
    declared_ids = {item["document_id"] for item in document["source_documents"]}
    if set(paths) - declared_ids:
        _issue(issues, "SOURCE_SET_MISMATCH", "$.source_documents",
               "An explicitly supplied source is not declared in the inventory.")
    for index, source in enumerate(document["source_documents"]):
        location = f"$.source_documents[{index}]"
        identity = {"document_id": source["document_id"], "declared_sha256": source["sha256"],
                    "observed_sha256": None, "hash_verified": False}
        report["original_sources"].append(identity)
        source_path = paths.get(source["document_id"])
        if source_path is None:
            _issue(issues, "SOURCE_CONTRACT_MISSING", location,
                   "An original source file was not explicitly supplied.", blocker=True)
            continue
        try:
            data = _read_bytes(Path(source_path))
        except FileNotFoundError:
            _issue(issues, "SOURCE_CONTRACT_MISSING", location,
                   "An original source file is missing.", blocker=True)
            continue
        except InvalidJSON as error:
            _issue(issues, str(error), location, "Original source exceeds the offline input limit.")
            continue
        except OSError:
            _issue(issues, "SOURCE_UNREADABLE", location,
                   "An original source could not be read.", blocker=True)
            continue
        identity["observed_sha256"] = hashlib.sha256(data).hexdigest()
        identity["hash_verified"] = identity["observed_sha256"] == source["sha256"]
        if not identity["hash_verified"]:
            _issue(issues, "SOURCE_HASH_MISMATCH", location,
                   "Original source bytes do not match their declared SHA256.")
    return _finish(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate inert offline contract documentation; never grant or execute.")
    parser.add_argument("inventory", nargs="?", type=Path)
    parser.add_argument("--sha256", help="Independent lowercase inventory SHA256 pin (required in source mode).")
    parser.add_argument("--source", action="append", default=[], metavar="ID=PATH",
                        help="Explicit local original source path; never taken from inventory contents.")
    parser.add_argument("--synthetic-fixture", action="store_true", help="Explicit synthetic tests only; does not validate source acceptance.")
    args = parser.parse_args(argv)
    sources: dict[str, Path] = {}
    argument_errors: list[dict[str, str]] = []
    for supplied in args.source:
        identity, separator, filename = supplied.partition("=")
        if not separator or not identity or not filename or identity in sources:
            _issue(argument_errors, "INVALID_SOURCE_ARGUMENT", "$",
                   "Source arguments require unique nonempty ID=PATH pairs.")
        else:
            sources[identity] = Path(filename)
    if argument_errors:
        report = _base_report(args.synthetic_fixture)
        report["issues"] = argument_errors
        report = _finish(report)
    else:
        report = validate_inventory(args.inventory, expected_sha256=args.sha256,
                                    source_paths=sources, synthetic=args.synthetic_fixture)
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["validation_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
