"""Load the fixed, inert S3 synthetic fixture with its original validator."""

import hashlib
import json
from pathlib import Path
from types import MappingProxyType

SOURCE_COMMIT = "88c411852d1a90e62ec71ab1c9ae2278f72d0c76"
INVENTORY_SHA256 = "40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4"
# Informational expected historical counts, never a claim of available records.
HISTORICAL_COUNTS = MappingProxyType({"actions": 70, "transitions": 58})
_UPSTREAM_ROOT = Path(__file__).resolve().parent / "upstream"
_PINS = MappingProxyType(
    {
        "__init__.py": "ae35be2a0ae110ebaaddd5e58f770d1002a20a22e6df4e3185d9c8dc55f13c81",
        "validator.py": "847118024daec38656a2829402af8cd8a2e7866b99ced3e382ad190538796834",
        "inventory.schema.json": "c0c64ab3454a9d6d4a153b9e7815aa91c7c842b7c07f0c6135f95966df7a3712",
        "synthetic_inventory.json": INVENTORY_SHA256,
        "synthetic_review_excerpt.json": "266e07ae6b229a19df2d11b8a9aa986e9cd468a05ecacfd7d22de3ebdd7b760d",
    }
)
_MAX_BYTES = 4 * 1024 * 1024


class SourceUnavailable(ValueError):
    """The bundled synthetic contracts cannot be trusted or validated."""


def _pinned_bytes(name: str) -> bytes:
    with (_UPSTREAM_ROOT / name).open("rb") as handle:
        data = handle.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES or hashlib.sha256(data).hexdigest() != _PINS[name]:
        raise SourceUnavailable("SOURCE_CONTRACT_UNAVAILABLE")
    return data


def load_inventory() -> dict:
    """Return a fresh validated synthetic document; accept no caller input.

    No runtime Git lookup, network call, arbitrary file path, or user policy is
    consulted. A valid document is still inert and does not approve U03/U10.
    """
    try:
        bundled = {name: _pinned_bytes(name) for name in _PINS}
        # Check the vendored implementation before its first import.
        from .upstream import validator

        inventory = json.loads(bundled["synthetic_inventory.json"].decode("utf-8"))
        if inventory["source_documents"] != [
            {
                "document_id": "synthetic-review",
                "sha256": _PINS["synthetic_review_excerpt.json"],
            }
        ]:
            raise SourceUnavailable("SOURCE_CONTRACT_UNAVAILABLE")
        if validator.inspect_structure(inventory, synthetic=True):
            raise SourceUnavailable("SOURCE_CONTRACT_UNAVAILABLE")
        # inspect_structure reads its sibling schema; retain its exact pin after
        # validation too rather than accepting a changed bundled schema.
        _pinned_bytes("inventory.schema.json")
        return inventory
    except (ImportError, OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise SourceUnavailable("SOURCE_CONTRACT_UNAVAILABLE") from error
