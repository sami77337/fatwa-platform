from abc import ABC, abstractmethod


class CollectionAuthority(ABC):
    """No public source, staff role or collection review grants these capabilities."""

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
        resource_sha256,
    ):
        """Literal True for an exact operation/resource in the current case scope."""
        raise NotImplementedError

    def projection_epoch(self):
        """Atomic side-effect-free revision of all permissions and their expiry."""
        from apps.casework.services import CaseConflict

        raise CaseConflict("collection_authority_snapshot_required")
