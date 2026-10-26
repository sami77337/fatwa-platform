"""Deterministic receipt over the existing entirely fabricated readiness fixture."""

import json
from hashlib import sha256

from apps.fast8_source_preflight.service import BASE_SHA, SCHEMA
from tests.source_readiness.fixtures import bundle

AS_OF = "2026-10-26T12:00:00Z"


def receipt_data():
    manifest, _, input_bytes, archive_bytes = bundle()
    manifest["dataset_id"] = "synthetic-receipt-readiness-v1"
    return {
        "schema": SCHEMA,
        "fabrication": "EXPLICIT_LOCAL_SYNTHETIC",
        "receipt_id": "synthetic-receipt-v1",
        "base_sha": BASE_SHA,
        "issued_at": "2026-10-26T00:00:00Z",
        "expires_at": "2026-10-27T00:00:00Z",
        "sources": [
            {
                "archive_id": "synthetic-archive-v1",
                "archive_name": "synthetic-مرجع.zip",
                "archive_size_bytes": len(archive_bytes),
                "input_size_bytes": len(input_bytes),
                "manifest": manifest,
                "ordering_claim": {
                    "kind": "source_order_unique_ascending",
                    "heading_count": manifest["spec"]["expected_rows"],
                    "input_sha256": manifest["spec"]["source_input_sha256"],
                },
            }
        ],
    }


def encode(data):
    # Deliberately preserve CRLF and Arabic in the fixture's exact-byte identity.
    return (
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).replace("\n", "\r\n")
        + "\r\n"
    ).encode("utf-8")


def fixture():
    raw = encode(receipt_data())
    return raw, sha256(raw).hexdigest()


if __name__ == "__main__":
    import sys

    sys.stdout.buffer.write(fixture()[0])
