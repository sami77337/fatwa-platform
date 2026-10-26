"""Bounded, exact comparison after authoritative replay of BOTH inputs.

The current replay contract accepts only this checkout's fixed snapshot. Thus
accepted pairs currently have no differences; this module never weakens replay
to accept historical, rehashed or caller-declared 'verified' bundles.
"""

import json
from hashlib import sha256

from . import services
from .services import ExportError


def _differences(before, after, path=()):
    """Exact typed values; path tokens avoid ambiguous dotted/indexed keys.

    Arrays retain service order. Missing and explicit null are distinct. Whole
    arrays are emitted on change so reference/revision positions are not joined
    using potentially duplicated external identities.
    """
    if type(before) is dict and type(after) is dict:
        changes = []
        for key in sorted(before.keys() | after.keys()):
            if key in before and key in after:
                changes.extend(_differences(before[key], after[key], (*path, key)))
            else:
                changes.append(
                    {
                        "path": [*path, key],
                        "before": {"present": key in before, "value": before.get(key)},
                        "after": {"present": key in after, "value": after.get(key)},
                    }
                )
        return changes
    # Canonical bytes also distinguish booleans from integers inside arrays.
    if services.encode_json(before) == services.encode_json(after):
        return []
    return [
        {
            "path": list(path),
            "before": {"present": True, "value": before},
            "after": {"present": True, "value": after},
        }
    ]


def _index(report):
    """Reject unsupported contracts and ambiguous joins even after replay."""
    if (
        report["schema"] != "synthetic-editorial-export.v1"
        or report["synthetic_only"] is not True
        or report["holds"] != list(services.HOLDS)
        or report["scope"] != "fixed_synthetic_fixtures_only_no_persisted_review"
    ):
        raise ExportError("compare: incompatible_contract")
    if len(report["cases"]) > services.MAX_CASES or len(report["batches"]) > services.MAX_BATCHES:
        raise ExportError("compare: inventory_limit")
    cases, batches = {}, {}
    for entry in report["cases"]:
        packet = entry["packet"]
        key = packet["identity"]["case_key"]
        if (
            type(key) is not str
            or not key
            or key in cases
            or entry["navigation"]["case_key"] != key
        ):
            raise ExportError("compare: ambiguous_case_identity")
        if (
            packet["schema"] != "synthetic-case-review-packet.v1"
            or packet["synthetic_only"] is not True
            or packet["holds"] != list(services.HOLDS)
        ):
            raise ExportError("compare: incompatible_packet")
        cases[key] = entry
    for batch in report["batches"]:
        key = batch["batch_id"]
        if type(key) is not str or not key or key in batches:
            raise ExportError("compare: ambiguous_batch_identity")
        batches[key] = batch
    return cases, batches


def _case_identity(entry):
    return {
        "identity": entry["packet"]["identity"],
        "packet_sha256": entry["packet_sha256"],
    }


def _members(cases, batch_id):
    return [
        entry["packet"]["identity"]
        for key, entry in sorted(cases.items())
        if entry["packet"]["identity"]["batch_id"] == batch_id
    ]


def _compare_reports(before, after):
    """Internal differ, never an alternate verification entry point."""
    old_cases, old_batches = _index(before)
    new_cases, new_batches = _index(after)
    changed_cases = []
    for key in sorted(old_cases.keys() & new_cases.keys()):
        old, new = old_cases[key], new_cases[key]
        changes = _differences(old, new)
        if not changes:
            continue
        groups = {"preparation": [], "reference": [], "source_provenance": [], "packet": []}
        for change in changes:
            path = change["path"]
            field = path[1] if path[0] == "packet" and len(path) > 1 else None
            if field in ("receipt", "preparation_errors", "intake_issues"):
                group = "preparation"
            elif field == "reference_verification":
                group = "reference"
            elif field in ("identity", "source", "intake"):
                group = "source_provenance"
            else:
                group = "packet"
            groups[group].append(change)
        changed_cases.append(
            {
                "case_key": key,
                "before_identity": old["packet"]["identity"],
                "after_identity": new["packet"]["identity"],
                "packet_sha256": {"before": old["packet_sha256"], "after": new["packet_sha256"]},
                "packet_digest_changed": old["packet_sha256"] != new["packet_sha256"],
                "changes": groups,
            }
        )
    changed_batches = []
    for key in sorted(old_batches.keys() & new_batches.keys()):
        changes = _differences(old_batches[key], new_batches[key])
        old_members, new_members = _members(old_cases, key), _members(new_cases, key)
        if changes or old_members != new_members:
            changed_batches.append(
                {
                    "batch_id": key,
                    "changes": changes,
                    "before_members": old_members,
                    "after_members": new_members,
                }
            )
    return {
        "cases": {
            "added": [
                _case_identity(new_cases[k]) for k in sorted(new_cases.keys() - old_cases.keys())
            ],
            "removed": [
                _case_identity(old_cases[k]) for k in sorted(old_cases.keys() - new_cases.keys())
            ],
            "changed": changed_cases,
        },
        "batches": {
            "added": [
                {"batch": new_batches[k], "members": _members(new_cases, k)}
                for k in sorted(new_batches.keys() - old_batches.keys())
            ],
            "removed": [
                {"batch": old_batches[k], "members": _members(old_cases, k)}
                for k in sorted(old_batches.keys() - new_batches.keys())
            ],
            "changed": changed_batches,
        },
        "report_metadata": _differences(
            {k: v for k, v in before.items() if k not in ("cases", "batches")},
            {k: v for k, v in after.items() if k not in ("cases", "batches")},
        ),
    }


def compare_exports(
    before: dict[str, bytes], after: dict[str, bytes], *, synthetic_fixtures_only: bool = False
) -> bytes:
    """Return canonical UTF-8 JSON, or fail without a partial comparison.

    No caller-supplied verifier, expected digest, fixture or verified flag is
    accepted. Both input snapshots pass the unchanged authoritative verifier
    before any external JSON is parsed. Existing input/output bounds apply.
    """
    services.require_development(synthetic_fixtures_only)
    if type(before) is not dict or type(after) is not dict:
        raise ExportError("compare: unexpected_files")
    before, after = before.copy(), after.copy()
    services.verify_export(before, synthetic_fixtures_only=True)
    services.verify_export(after, synthetic_fixtures_only=True)
    try:
        old_report, new_report = json.loads(before["report.json"]), json.loads(after["report.json"])
        result = _compare_reports(old_report, new_report)
        result["manifest"] = _differences(
            json.loads(before["manifest.json"]), json.loads(after["manifest.json"])
        )
        result.update(
            schema="synthetic-editorial-export-comparison.v1",
            synthetic_only=True,
            holds=services.HOLDS,
            identical=before == after,
            verification="both inputs passed exact-byte replay against this checkout's fixed synthetic services",
            identity_rule="exact case_key; external_id is never a join key; identity field changes remain explicit",
            inputs={
                side: {
                    name: {"bytes": len(files[name]), "sha256": sha256(files[name]).hexdigest()}
                    for name in services.FILE_NAMES
                }
                for side, files in (("before", before), ("after", after))
            },
        )
        return services.encode_json(result)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ExportError):
            raise
        raise ExportError("compare: incompatible_contract") from exc
