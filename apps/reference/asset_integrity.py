"""Exact source-byte pins for the five fixed reference assets.

This is a bounded runtime integrity check, not a full served-asset lock:
django_htmx remains separately allowlisted until its exact authorized bytes
and package provenance are established.
"""
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

REFERENCE_ASSET_MANIFEST = MappingProxyType({
    "reference/catalog.js": (29665, "d78cff1450d64547a1cd04dcbc48a7df57dd1125d39808e3f90f8dd5c6bd6566"),
    "reference/django-api.mjs": (9615, "6df97f43e7558e20f839c0a9370694273f5ace532fe532a667b3a2f79c57a915"),
    "reference/tree.js": (1066, "9463a1cb27e922d7e54941aeec090a843d2f3dff3f62915e8398331a2fe4f173"),
    "reference/catalog.css": (6616, "bc26502e83911a7b198b4d68183db3d78c44816f8f665d1302f950daef74f46c"),
    "reference/style.css": (1253, "6f58de051096896a45078dee82f11a6b29d810a4007675402df0889d48c63a65"),
})


class AssetIntegrityError(Exception):
    """A pinned reference asset is missing or has changed."""


def verified_reference_asset(asset: str, filename: str) -> bytes:
    """Return exact pinned bytes, or fail closed before serving the asset."""
    expected = REFERENCE_ASSET_MANIFEST.get(asset)
    if expected is None:
        raise AssetIntegrityError("asset_not_pinned")
    expected_size, expected_sha256 = expected
    try:
        with Path(filename).open("rb") as source:
            payload = source.read(expected_size + 1)
    except OSError as exc:
        raise AssetIntegrityError("asset_unavailable") from exc
    if len(payload) != expected_size or sha256(payload).hexdigest() != expected_sha256:
        raise AssetIntegrityError("asset_integrity_mismatch")
    return payload
