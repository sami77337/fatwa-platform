"""Byte-pinned asset guard for the loopback-only editorial preview stylesheet.

The manifest pins the *original* 806 bytes committed with Wave7. Do not
normalize whitespace, decode/re-encode CSS, or silently update this digest.
An intended asset update requires a separately reviewed digest change.
"""

from hashlib import sha256
from pathlib import Path


PREVIEW_CSS_PATH = Path(__file__).with_name("preview.css")
PREVIEW_CSS_SIZE = 806
PREVIEW_CSS_SHA256 = "733933993a8f9bd05e5ce6c57d8b646e8518cf08581cfc17fbf59a8e5873eb38"


class AssetIntegrityError(Exception):
    """A pinned development-only asset is missing or has changed."""


def verified_preview_css() -> bytes:
    """Return precisely the pinned bytes, or fail closed before serving CSS.

    The bounded read prevents a corrupted oversized file from being loaded in
    full. Exactly the same bytes that were hashed are returned to the caller.
    """
    try:
        with PREVIEW_CSS_PATH.open("rb") as source:
            payload = source.read(PREVIEW_CSS_SIZE + 1)
    except OSError as exc:
        raise AssetIntegrityError("preview_css_unavailable") from exc
    if len(payload) != PREVIEW_CSS_SIZE or sha256(payload).hexdigest() != PREVIEW_CSS_SHA256:
        raise AssetIntegrityError("preview_css_integrity_mismatch")
    return payload
