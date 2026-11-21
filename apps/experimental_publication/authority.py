"""Separate server-configured publication grants, never inferred from a role."""

from abc import ABC, abstractmethod


class PublicationAuthority(ABC):
    def projection_epoch(self):
        """Opt-in pure revision for composed operational reads and transitions.

        Legacy scalar MUFTI callers retain their existing contract. A new
        operational manager must deny unversioned policies; READ and REVIEW
        also require explicit grants on that path.
        """
        from apps.casework.services import CaseConflict

        raise CaseConflict("publication_policy_snapshot_required")

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        """Return exactly True for a current, explicit synthetic publication grant."""
        raise NotImplementedError
