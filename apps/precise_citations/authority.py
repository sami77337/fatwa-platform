from abc import ABC, abstractmethod


class CitationAuthority(ABC):
    """Independent exact-resource operations, never a publication or delivery grant."""

    @abstractmethod
    def permits(
        self,
        *,
        provider_id,
        subject_id,
        auth_epoch,
        case_ref,
        action,
        kind,
        resource_id,
        resource_digest,
    ):
        raise NotImplementedError

    def projection_epoch(self):
        """Atomic pure revision including permission changes and expiration."""
        raise NotImplementedError
