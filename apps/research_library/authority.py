"""Independent exact-material permissions; a source label never grants a use."""

from abc import ABC, abstractmethod


class LibraryAuthority(ABC):
    @abstractmethod
    def permits(
        self,
        *,
        provider_id,
        subject_id,
        auth_epoch,
        case_ref,
        action,
        namespace,
        external_id,
        version_digest,
    ):
        """Return literal True for this current actor, material and operation."""
        raise NotImplementedError

    def projection_epoch(self):
        """Side-effect-free atomic revision of all grant inputs, including expiry."""
        from apps.casework.services import CaseConflict

        raise CaseConflict("library_policy_snapshot_required")
