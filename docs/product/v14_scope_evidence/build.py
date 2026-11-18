"""Preserve all V13 scope rows and attribute the local source-lineage correction.

Documentary scaffolding only: no V14 runtime or source-byte execution is inferred.
Uses stdlib and immutable git objects; all generated output stays in this folder.
"""

import csv
import hashlib
import io
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE_SHA = "1f08cbb7166f70ec340c495da33ccfc1eda9534e"
COUNTS = {"PARTIAL": 303, "DECISION": 52, "NOT_IMPLEMENTED": 168, "OUT_OF_SCOPE": 33}


def read(name):
    return json.loads((HERE / name).read_text())


def baseline():
    manifest = read("baseline_manifest.json")
    assert manifest["base_sha"] == BASE_SHA
    assert manifest["prefix"] == "docs/product/v13_scope_evidence/"
    result = {}
    for name, expected in manifest["files"].items():
        assert name in {
            "matrix.json",
            "summary.json",
            "source_bytes.json",
            "execution_history.json",
        }
        raw = subprocess.check_output(
            ["git", "show", f"{BASE_SHA}:{manifest['prefix']}{name}"], cwd=ROOT
        )
        assert hashlib.sha256(raw).hexdigest() == expected, (name, "baseline changed")
        result[name] = json.loads(raw)
    assert set(result) == {
        "matrix.json",
        "summary.json",
        "source_bytes.json",
        "execution_history.json",
    }
    rows = result["matrix.json"]
    assert [int(row["original_id"]) for row in rows] == list(range(1, 557))
    assert Counter(row["engineering_status"] for row in rows) == COUNTS
    return result


def validate_source(receipt):
    assert receipt["attribution"] == "PARENT_LOCAL_VERIFICATION_NOT_CLOUD_REEXECUTION"
    assert receipt["reported_report"] == "V13_SOURCE_LINEAGE_ADDENDUM.md"
    assert receipt["report_file_received_here"] is False
    assert receipt["receipt_bytes_inspected_here"] is False
    assert receipt["historical_files_modified"] is False
    assert (
        receipt["reported_result_sha256"]
        == "a930cf91421eb6ad232bbccc75a1c6ffa012bdcc39dcdeedb28fecfbdcf3531b"
    )
    expected = {
        "docx": (56895, "436751386501bf53c6a7f39bb21ee1eec85e6d34f3326fe528cf38e6bc6c80ff"),
        "reference_xlsx": (
            211695,
            "874326f71ded93a1a4ccb11a9038429a8f604d1e9e23acef7e8c52327b42969e",
        ),
        "registry479": (530248, "48024cb9c1693d64c6e2c22928748f123c819ba37428016ca7cd8a26e2d175fb"),
        "pinned_text": (316943, "5b810ace8c846fb1437165c36a2884f3b0134b3b3c51149290e125f95d28b8c7"),
    }
    for name, (size, digest) in expected.items():
        item = receipt["artifacts"][name]
        assert (item["bytes"], item["sha256"]) == (size, digest)
        assert item["status"] == "SOURCE_BYTES_VERIFIED_LOCALLY_BY_PARENT"
    assert receipt["artifacts"]["reference_xlsx"]["role"] == "DERIVED_REFERENCE_WORKBOOK"
    assert receipt["artifacts"]["reference_xlsx"]["sheets"] == 8
    assert receipt["artifacts"]["historical_xlsx"] == {
        "bytes": 384127,
        "sheets": 5,
        "different_artifact_from_reference": True,
        "transformation_chain": "NOT_REPRODUCED",
    }
    assert receipt["reported_matches"]["numbered_texts"] == 556
    assert receipt["reported_matches"]["registry_entries"] == 479
    assert (
        receipt["reported_matches"]["compared_matrix_sha"]
        == "5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8"
    )
    differences = receipt["serialization_differences"]
    assert differences["count"] == 17 and differences["cells"] == "C5:C21"
    assert differences["whole_string_equality"] is False
    assert receipt["formula_cells"] == {
        "count": 9,
        "comparison": "SAVED_VALUES_ONLY",
        "recalculated": False,
    }
    assert receipt["boundaries"] == dict.fromkeys(
        [
            "cloud_source_bytes_verified",
            "source_originals_uploaded",
            "authoring_provenance_established",
            "semantic_approval",
            "acceptance",
            "workbook_transformation_reproduced",
        ],
        False,
    )


def validate_evidence(value):
    # Intentionally closed until exact integrated-head evidence is reviewed.
    # A later bounded-evidence contract must replace this scaffold explicitly;
    # merely inserting a SHA or a green workflow cannot credit a requirement.
    assert value == {
        "campaign": "V14",
        "state": "PENDING_INTEGRATED_RUNTIME_EVIDENCE",
        "groups": [],
        "status_upgrades": 0,
        "acceptance": "HOLD",
        "new_percentage": None,
    }, "V14 evidence is pending; no unreviewed runtime credit"


def outputs():
    prior = baseline()
    validate_source(read("source_lineage.json"))
    validate_evidence(read("evidence.json"))
    rows = prior["matrix.json"]
    for row in rows:
        assert "v14" not in row
        row["v14"] = {
            "state": "PENDING_INTEGRATED_RUNTIME_EVIDENCE",
            "evidence_ids": [],
            "evidence_shas": [],
            "status_upgrade": False,
            "source_lineage_basis": "PARENT_LOCAL_ATTESTATION_2026-11-18",
            "word_locator_status": "REPORTED_MATCH_BY_PARENT_NOT_CLOUD_REEXECUTED",
        }
    summary = {
        "base_sha": BASE_SHA,
        "owner_points": 556,
        "specification_clauses": 479,
        "decision_ids": 72,
        "decision_occurrences": 77,
        "preserved_status_counts": COUNTS,
        "v14_verified_points": 0,
        "v14_runtime_state": "PENDING_INTEGRATED_RUNTIME_EVIDENCE",
        "status_upgrades": 0,
        "acceptance": "HOLD",
        "new_percentage": None,
        "gate_b": "NOT_PASSED",
        "gates_c_d_e": "HOLD",
        "phase01": "BLOCKED",
        "production": "NOT_DEPLOYED",
        "source_status": "PARENT_LOCAL_ATTESTATION",
        "cloud_source_byte_verification": False,
    }
    csvfile = io.StringIO(newline="")
    writer = csv.writer(csvfile)
    writer.writerow(["point", "SPEC", "decisions", "preserved_status", "V14", "baseline_sha"])
    md = [
        "# V14 scope trace — pending runtime evidence",
        "",
        f"Pinned V13 baseline: `{BASE_SHA}`.",
        "All original fields, historic evidence and classifications remain in matrix.json.",
        "This table grants no V14 runtime credit or acceptance.",
        "",
        "| Point | SPEC | Decisions | Preserved status | V14 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        specs = ", ".join(
            dict.fromkeys(row["direct_spec_ids"] + row["additional_reverse_spec_ids"])
        )
        decisions = ", ".join(row["decision_ids"])
        fields = [row["original_id"], specs, decisions, row["engineering_status"], "PENDING"]
        writer.writerow([*fields, BASE_SHA])
        md.append("| " + " | ".join(fields) + " |")
    return {
        "matrix.json": json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        "summary.json": json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        "matrix.csv": csvfile.getvalue(),
        "MATRIX.md": "\n".join(md) + "\n",
    }


def main():
    assert sys.argv[1:] in ([], ["--check"])
    generated = outputs()
    for name, content in generated.items():
        if "--check" in sys.argv:
            assert (HERE / name).read_bytes() == content.encode(), (
                name,
                "generated output differs",
            )
        else:
            (HERE / name).write_bytes(content.encode())
    print(
        "V14 documentary scaffold: 556 preserved rows; source attribution checked; runtime PENDING"
    )


if __name__ == "__main__":
    main()
