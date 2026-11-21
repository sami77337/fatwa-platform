from abc import ABC, abstractmethod


class TeachingAuthority(ABC):
    """Independent exact-resource grants; absent authority denies every operation."""

    @abstractmethod
    def projection_epoch(self):
        """Pure atomic state for every actor, resource, action and expiry input."""
        raise NotImplementedError

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
        """READ/WRITE/REVIEW/APPROVE/RELEASE/WITHDRAW, READ_SOURCE or
        PUBLIC_LESSON_CONTENT for this exact current resource. No inferred grants.
        """
        raise NotImplementedError

    @abstractmethod
    def grant_deadline(self, **values):
        """Aware finite current deadline for the same exact operation, or None."""
        raise NotImplementedError
