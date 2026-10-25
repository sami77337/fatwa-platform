"""Read inherited owner *metadata* only; never call source importer execution."""

import json
from dataclasses import asdict
from pathlib import PurePosixPath

from apps.reference.records import CatalogSpec
from tools.fiqh_import import load_manifest
from tools.fiqh_import.book622 import (
    ARCHIVE_SHA256,
    EDITION_KEY,
    INPUT_MEMBER,
    MANIFEST,
    MAPPED_CHECKSUM,
)
from tools.fiqh_import.owner_r1 import INPUT_PINS


def pinned_owner_manifest() -> bytes:
    """Expose existing pins without manufacturing a local numeric edition ID.

    The owner adapter defines this CatalogSpec mapping. Inherited assertions are
    deliberately distinct from observed hashes; none of these bytes are raw proof.
    """
    metadata = load_manifest(MANIFEST)
    if (
        metadata.source_kind != "owner_supplied"
        or metadata.book_id != "622"
        or metadata.input_sha256 != INPUT_PINS["jsonl"]
        or (metadata.expected_nodes, metadata.expected_roots, metadata.expected_max_depth)
        != (11397, 32, 5)
    ):
        raise ValueError("inherited_owner_metadata_mismatch")
    spec = CatalogSpec(
        source_namespace="shamela",
        source_book_id=metadata.book_id,
        work_title="كشاف القناع عن متن الإقناع",
        madhhab="حنبلي",
        edition_key=EDITION_KEY,
        edition_title=metadata.edition,
        publisher="وزارة العدل السعودية",
        source_archive_sha256=ARCHIVE_SHA256,
        source_input_sha256=metadata.input_sha256,
        input_name=PurePosixPath(INPUT_MEMBER).name,
        expected_rows=metadata.expected_nodes,
        expected_roots=metadata.expected_roots,
        expected_max_depth=metadata.expected_max_depth,
    )
    return json.dumps(
        {
            "schema": "fatwa.source-readiness.manifest.v1",
            "dataset_id": metadata.dataset_id,
            "source_kind": "owner_supplied",
            "edition_id": None,
            "spec": asdict(spec),
            "catalog_checksum": MAPPED_CHECKSUM,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
