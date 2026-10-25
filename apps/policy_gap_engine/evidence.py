"""Fixed FAST5/S3 evidence adapter. No caller-selected policies or source paths."""

import hashlib
import json
from pathlib import Path

from apps.permission_lab import sources


def _empty_evidence() -> dict:
    return {
        "status": "UNAVAILABLE",
        "reason_codes": ["EVIDENCE_MISSING", "POLICY_PENDING", "SOURCE_CONTRACT_UNAVAILABLE"],
        "policy_approval_verified": False,
        "source_acceptance_passed": False,
        "provenance": {
            "source_commit": sources.SOURCE_COMMIT,
            "inventory_sha256": sources.INVENTORY_SHA256,
            "fixture_kind": "SYNTHETIC",
            "hashes_verified": False,
        },
        "coverage": {
            "synthetic": None,
            "historical_actions": {"expected": sources.HISTORICAL_COUNTS["actions"], "supplied": 0},
            "historical_transitions": {
                "expected": sources.HISTORICAL_COUNTS["transitions"],
                "supplied": 0,
            },
            # Aggregate expectations from AGENTS.md, not invented clause contents.
            "U03": {"expected": 48, "supplied": 0, "approved": 0},
            "U10": {"expected": 28, "supplied": 0, "approved": 0},
        },
        "records": [],
        "gaps": [
            {"evidence": name, "status": "EVIDENCE_MISSING"}
            for name in (
                "historical_actions",
                "historical_transitions",
                "U03",
                "U10",
                "reviewed_original_sources",
                "owner_acceptance",
            )
        ],
    }


def load_evidence() -> tuple[dict, dict]:
    """Check pins, original S3 validation, policy tokens and synthetic ID membership.

    Membership in the invented excerpt is NOT a reviewed-source content binding.
    Hash/source failures raise the existing closed failure, never partial evidence.
    """
    inventory = sources.load_inventory()  # Pins the original validator before import.
    from apps.permission_lab.upstream import validator

    root = Path(sources.__file__).resolve().parent / "upstream"
    try:
        validation = validator.validate_inventory(
            root / "synthetic_inventory.json",
            expected_sha256=sources.INVENTORY_SHA256,
            source_paths={"synthetic-review": root / "synthetic_review_excerpt.json"},
            synthetic=True,
        )
        if not validation["validation_passed"]:
            raise sources.SourceUnavailable("SOURCE_CONTRACT_UNAVAILABLE")
        declared = inventory["source_documents"][0]
        with (root / "synthetic_review_excerpt.json").open("rb") as handle:
            raw = handle.read(4 * 1024 * 1024 + 1)
        if hashlib.sha256(raw).hexdigest() != declared["sha256"]:
            raise sources.SourceUnavailable("SOURCE_CONTRACT_UNAVAILABLE")
        excerpt = json.loads(raw.decode("utf-8"))
        ids = excerpt["records"]
        if (
            excerpt["fixture_kind"] != "SYNTHETIC"
            or type(ids) is not list
            or any(type(value) is not str for value in ids)
            or len(set(ids)) != len(ids)
        ):
            raise sources.SourceUnavailable("SOURCE_CONTRACT_UNAVAILABLE")
        records = []
        for category, key in (("actions", "action_id"), ("transitions", "transition_id")):
            for row in inventory[category]:
                ref = row["source_ref"]
                if (
                    ref["document_id"] != declared["document_id"]
                    or ref["record_id"] not in ids
                    or row["policy_token"] != inventory["policy"]["policy_token"]
                ):
                    raise sources.SourceUnavailable("SOURCE_CONTRACT_UNAVAILABLE")
                records.append(
                    {
                        "id": row[key],
                        "category": category,
                        "source_ref": dict(ref),
                        "policy_token": row["policy_token"],
                        "policy_status": "POLICY_PENDING",
                        "binding_scope": "SYNTHETIC_ID_MEMBERSHIP_ONLY",
                        "candidate_roles": [item["name"] for item in row["candidate_principals"]],
                    }
                )
        report = _empty_evidence()
        report.update(
            status="SYNTHETIC_ONLY",
            reason_codes=["EVIDENCE_MISSING", "POLICY_PENDING"],
            records=sorted(records, key=lambda row: (row["category"], row["id"])),
        )
        report["provenance"].update(
            hashes_verified=True,
            policy_token=inventory["policy"]["policy_token"],
            source_documents=[dict(declared)],
            validator_scope=validation["validation_scope"],
            reviewed_record_content_binding=validation["record_content_binding"],
        )
        report["coverage"]["synthetic"] = {
            "actions": len(inventory["actions"]),
            "transitions": len(inventory["transitions"]),
            "source_id_membership_verified": len(records),
        }
        return inventory, report
    except (ImportError, OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise sources.SourceUnavailable("SOURCE_CONTRACT_UNAVAILABLE") from error


def inspect_evidence() -> dict:
    """Return fresh diagnostic evidence; a missing artifact cannot count as coverage."""
    try:
        return load_evidence()[1]
    except sources.SourceUnavailable:
        return _empty_evidence()
