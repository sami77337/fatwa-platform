"""Validate the pinned documentary package; does not execute product tests."""

import json
from pathlib import Path

import build
import p1

HERE = Path(__file__).resolve().parent


def validate():
    manifest = build.read("source_manifest.json")
    assert manifest["evidence_sha"] == build.SHA
    for path, expected in manifest["extraction_sha256"].items():
        assert build.digest((HERE / path).read_bytes()) == expected, f"source drift: {path}"
    p1_manifest = build.read("p1_manifest.json")
    assert p1_manifest["head_sha"] == p1.P1_SHA
    for path, expected in p1_manifest["extraction_sha256"].items():
        assert build.digest((HERE / path).read_bytes()) == expected, f"P1 source drift: {path}"
    for path, expected in p1_manifest["preserved_baseline_files"].items():
        raw = build.pinned("docs/product/v12_scope_evidence/" + path, sha=p1.P1_SHA)
        assert build.digest(raw) == expected, f"baseline attribution drift: {path}"
    products = build.build()
    for name, text in products.items():
        assert (HERE / name).read_bytes() == text.encode(), f"derived drift: {name}"
    matrix = json.loads(products["matrix.json"])
    groups = {g["id"]: g for g in json.loads(products["evidence.json"])}
    assert len(matrix) == 556
    for row in matrix:
        assert row["engineering_status"] in build.STATES
        assert row["acceptance"] == "HOLD"
        assert row["assessed_p1"] == bool(row["p1_evidence_ids"])
        assert row["engineering_status"] == row["p0_engineering_status"]
        assert row["evidence_shas"] == [build.SHA] + ([p1.P1_SHA] if row["assessed_p1"] else [])
        assert row["evidence_sha"] == build.SHA
        if row["engineering_status"] == "PARTIAL":
            assert row["evidence_ids"], row["original_id"]
        if row["engineering_status"] == "COMPLETE":
            raise AssertionError("No full-requirement closure evidence has been reviewed in P2")
        for ident in row["evidence_ids"]:
            assert int(row["original_id"]) in groups[ident]["owner_points"]
            assert groups[ident]["remaining"] and groups[ident]["code"] and groups[ident]["tests"]
    print(
        "PASS: source hashes, 556/479 fidelity, all pinned references, HOLD, P1 exact-head attribution and deterministic outputs"
    )


if __name__ == "__main__":
    validate()
