"""Separate finite maintenance mandates; no source, processing or scholarly grant."""

from abc import ABC, abstractmethod

from apps.record_suppression.authority import Grant

__all__ = ("Grant", "DerivedAuthority")


class DerivedAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Pure atomic revision of all grants, exact choices and expiry."""
        raise NotImplementedError

    @abstractmethod
    def resources(self, *, provider_id, subject_id, auth_epoch, role):
        """Finite tuple of (SEARCH_INDEX | AI_CANDIDATES, exact header UUID)."""
        raise NotImplementedError

    @abstractmethod
    def authorize(self, *, provider_id, subject_id, auth_epoch, role, action, resource):
        """ENTER / READ_AUDIT / CLEAR / REBUILD / RECONCILE are independent.

        Every resource includes the immutable owner header and current payload
        and clearance pins. REBUILD never substitutes for current source read,
        search-rebuild, AI USE or per-provider PROCESS_CONTEXT authorization.
        """
        raise NotImplementedError
