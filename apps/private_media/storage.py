"""Private storage seam: callers authorize scope before reading; adapters never return URLs.

The shipped adapter packages immutable database bytes. A future object-storage
adapter must preserve this integrity contract and define its own durable pointer
schema/migration; no cloud configuration or credentials are supplied here.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256

from django.conf import settings

from .validation import MediaValidationError, ValidatedMedia


@dataclass(frozen=True)
class StoredOriginal:
    backend: str
    key: str
    sha256: str
    size: int
    inline: bytes | None = None


class PrivateStorage(ABC):
    @abstractmethod
    def put(self, media: ValidatedMedia) -> StoredOriginal:
        """Store an immutable original under a nonpublic reference, without overwriting."""

    @abstractmethod
    def get(self, original: StoredOriginal) -> bytes:
        """Read exact private bytes; implementations must not produce public URLs."""


class InlineDatabaseStorage(PrivateStorage):
    """The returned inline bytes are persisted in the caller's immutable ORM row."""

    def put(self, media: ValidatedMedia) -> StoredOriginal:
        return StoredOriginal(
            "inline-database-v1", media.sha256, media.sha256, media.size, media.raw
        )

    def get(self, original: StoredOriginal) -> bytes:
        if original.backend != "inline-database-v1" or type(original.inline) is not bytes:
            raise MediaValidationError("private_storage_unavailable")
        return verify_original(original.inline, original.sha256, original.size)


def verify_original(raw: bytes, digest: str, size: int) -> bytes:
    if type(raw) is not bytes or len(raw) != size or sha256(raw).hexdigest() != digest:
        raise MediaValidationError("private_original_integrity_failed")
    return raw


def configured_storage() -> PrivateStorage:
    storage = getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None)
    if storage is None:
        return InlineDatabaseStorage()
    if not isinstance(storage, PrivateStorage):
        raise MediaValidationError("private_storage_unavailable")
    return storage
