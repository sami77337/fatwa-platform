"""Exact expiring public-tool grants; never inferred from reading permission."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReaderGrant:
    publication_id: str
    content_sha256: str
    action: str
    provider_id: str
    subject_id: str
    auth_epoch: str
    valid_until: datetime


class ReaderToolsAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Pure atomic revision of every grant, actor binding and expiry input."""
        raise NotImplementedError

    @abstractmethod
    def grant(self, *, publication_id, content_sha256, action):
        """ReaderGrant for this exact action/resource, or None for no permission.

        SAVE_REFERENCE, SHARE_LINK, PRINT and DOWNLOAD_TEXT are separate. A grant
        carries its current scoped MUFTI authorizer, not an anonymous staff role.
        It cannot replace current publication approval, PreviewPolicy or source
        rights. No requester token, private case or bulk export is accepted.
        """
        raise NotImplementedError
