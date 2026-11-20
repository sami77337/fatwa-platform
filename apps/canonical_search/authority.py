"""Search permissions never grant source access, publication, or scholarly approval."""

from abc import ABC, abstractmethod

from apps.casework.services import CaseConflict


class SearchAuthority(ABC):
    def projection_epoch(self):
        """Pure atomic revision of all permission inputs, including expiry.

        Composed readers require this capability. A callback may not conceal a
        change by returning the same revision; missing capability fails closed.
        """
        raise CaseConflict("search_policy_snapshot_required")

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        """Literal True for VIEW, REBUILD, SEARCH, or OPEN on this exact case."""
        raise NotImplementedError
