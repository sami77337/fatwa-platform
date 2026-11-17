"""Separate server-configured publication grants, never inferred from a role."""

from abc import ABC, abstractmethod


class PublicationAuthority(ABC):
    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        """Return exactly True for a current, explicit synthetic publication grant."""
        raise NotImplementedError
