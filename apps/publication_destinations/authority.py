"""Exact, finite destination grants, independently configured on the server."""

from abc import ABC, abstractmethod


class DestinationAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Pure atomic revision of every grant, actor, scope and expiry input."""
        raise NotImplementedError

    @abstractmethod
    def permits(
        self,
        *,
        provider_id,
        subject_id,
        auth_epoch,
        case_ref,
        destination,
        action,
        resource_id,
        resource_sha256,
    ):
        """READ/SELECT/REVIEW/APPROVE/PREPARE/OBSERVE/WITHDRAW; no role inference."""
        raise NotImplementedError

    @abstractmethod
    def grant_deadline(self, **values):
        """Aware finite deadline for this exact grant, or None."""
        raise NotImplementedError
